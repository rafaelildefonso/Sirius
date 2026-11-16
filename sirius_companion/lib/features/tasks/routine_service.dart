import 'dart:convert';

import 'package:drift/drift.dart';
import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import '../../core/storage/database/database.dart';
import 'task_alarm_service.dart';

typedef RoutineOccurrenceCreator =
    Future<void> Function({
      required String remoteId,
      required String title,
      required DateTime dueAt,
      required String routineId,
      required String alertMode,
    });

/// Local-first routine definitions. Each date has a stable task id, so a
/// completed occurrence remains in scheduled_tasks as durable history.
class RoutineService {
  RoutineService._();

  static AppDatabase _db = AppDatabase();
  static RoutineOccurrenceCreator _createOccurrence =
      TaskAlarmService.createRoutineOccurrence;
  static Future<void> Function(String) _cancelOccurrence =
      TaskAlarmService.cancelAlarm;
  static Future<void> Function(String) _completeOccurrence = (id) =>
      TaskAlarmService.markDone(id, sync: false);
  static const weekdays = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
  static const modes = {'none', 'notification', 'alarm', 'call'};

  @visibleForTesting
  static void configureForTesting({
    required AppDatabase database,
    required RoutineOccurrenceCreator createOccurrence,
    required Future<void> Function(String) cancelOccurrence,
    required Future<void> Function(String) completeOccurrence,
  }) {
    _db = database;
    _createOccurrence = createOccurrence;
    _cancelOccurrence = cancelOccurrence;
    _completeOccurrence = completeOccurrence;
  }

  static bool isScheduledOn(List<int> weekdays, DateTime date) =>
      weekdays.contains(date.weekday % 7);

  static DateTime occurrenceDateTime(DateTime date, String time) {
    final parts = time.split(':');
    return DateTime(
      date.year,
      date.month,
      date.day,
      int.parse(parts[0]),
      int.parse(parts[1]),
    );
  }

  static String occurrenceId(String routineId, DateTime date) =>
      '${routineId}_${date.year.toString().padLeft(4, '0')}'
      '${date.month.toString().padLeft(2, '0')}'
      '${date.day.toString().padLeft(2, '0')}';

  static Future<List<Map<String, dynamic>>> list() async {
    final rows = await (_db.select(
      _db.routineDefinitions,
    )..orderBy([(row) => OrderingTerm.asc(row.createdAt)])).get();
    return rows
        .map(
          (row) => {
            ...Map<String, dynamic>.from(jsonDecode(row.payloadJson)),
            'id': row.id,
            'enabled': row.enabled,
          },
        )
        .toList();
  }

  static Future<(Map<String, dynamic>?, String?)> create(
    Map<String, dynamic> input,
  ) async {
    final normalized = _normalize(input);
    if (normalized.$2 != null) return (null, normalized.$2);
    final id = const Uuid().v4();
    final now = DateTime.now();
    await _db
        .into(_db.routineDefinitions)
        .insert(
          RoutineDefinitionsCompanion.insert(
            id: id,
            payloadJson: jsonEncode(normalized.$1),
            createdAt: now,
            updatedAt: now,
          ),
        );
    await generateUpcomingOccurrences();
    return ({...normalized.$1, 'id': id, 'enabled': true}, null);
  }

  static Future<bool> update(String id, Map<String, dynamic> input) async {
    final row = await (_db.select(
      _db.routineDefinitions,
    )..where((item) => item.id.equals(id))).getSingleOrNull();
    if (row == null) return false;
    final current = Map<String, dynamic>.from(jsonDecode(row.payloadJson));
    final normalized = _normalize({...current, ...input});
    if (normalized.$2 != null) return false;
    await _cancelFutureOccurrences(id);
    await (_db.update(
      _db.routineDefinitions,
    )..where((item) => item.id.equals(id))).write(
      RoutineDefinitionsCompanion(
        payloadJson: Value(jsonEncode(normalized.$1)),
        updatedAt: Value(DateTime.now()),
      ),
    );
    if (row.enabled) await generateUpcomingOccurrences();
    return true;
  }

  static Future<bool> setEnabled(String id, bool enabled) async {
    final updated =
        await (_db.update(
          _db.routineDefinitions,
        )..where((item) => item.id.equals(id))).write(
          RoutineDefinitionsCompanion(
            enabled: Value(enabled),
            updatedAt: Value(DateTime.now()),
          ),
        );
    if (updated == 0) return false;
    if (!enabled) {
      await _cancelFutureOccurrences(id);
    } else {
      await generateUpcomingOccurrences();
    }
    return true;
  }

  static Future<bool> delete(String id) async {
    final row = await (_db.delete(
      _db.routineDefinitions,
    )..where((item) => item.id.equals(id))).go();
    if (row == 0) return false;
    // Future occurrences are removed; completed occurrence rows are retained.
    await _cancelFutureOccurrences(id);
    return true;
  }

  static Future<List<ScheduledTask>> occurrences(
    DateTime start,
    int days,
  ) async {
    final end = DateTime(start.year, start.month, start.day + days);
    return (_db.select(_db.scheduledTasks)
          ..where(
            (task) =>
                task.source.equals('routine') &
                task.dueAt.isBiggerOrEqualValue(
                  DateTime(start.year, start.month, start.day),
                ) &
                task.dueAt.isSmallerThanValue(end),
          )
          ..orderBy([(task) => OrderingTerm.asc(task.dueAt)]))
        .get();
  }

  static Future<void> complete(String occurrenceId) async {
    final row = await (_db.select(
      _db.scheduledTasks,
    )..where((task) => task.remoteId.equals(occurrenceId))).getSingleOrNull();
    if (row == null || row.status == 'done') return;
    await _completeOccurrence(occurrenceId);
  }

  /// Materialize two local weeks on app start and after each definition change.
  /// DateTime constructors use the current local zone and account for DST when
  /// each individual day's local alarm time is built.
  static Future<void> generateUpcomingOccurrences({DateTime? now}) async {
    final clock = now ?? DateTime.now();
    final from = DateTime(clock.year, clock.month, clock.day);
    final definitions = await (_db.select(
      _db.routineDefinitions,
    )..where((item) => item.enabled.equals(true))).get();
    for (final row in definitions) {
      final definition = Map<String, dynamic>.from(jsonDecode(row.payloadJson));
      final days = (definition['weekdays'] as List)
          .cast<num>()
          .map((d) => d.toInt())
          .toSet();
      for (var offset = 0; offset < 14; offset++) {
        final date = from.add(Duration(days: offset));
        if (!isScheduledOn(days.toList(), date)) continue;
        final due = occurrenceDateTime(date, definition['time'] as String);
        await _createOccurrence(
          remoteId: occurrenceId(row.id, date),
          routineId: row.id,
          title: definition['name'] as String,
          dueAt: due,
          alertMode: definition['alert_mode'] as String,
        );
      }
    }
  }

  static Future<void> _cancelFutureOccurrences(String routineId) async {
    final now = DateTime.now();
    final rows =
        await (_db.select(_db.scheduledTasks)..where(
              (task) =>
                  task.recurrenceId.equals(routineId) &
                  task.status.isNotIn(['done', 'dismissed']),
            ))
            .get();
    for (final task in rows) {
      final retryRow = await _db
          .customSelect(
            'SELECT sirius_call_retry_at FROM scheduled_tasks WHERE remote_id = ?',
            variables: [Variable(task.remoteId)],
          )
          .getSingleOrNull();
      final retryAt = DateTime.tryParse(
        retryRow?.data['sirius_call_retry_at']?.toString() ?? '',
      );
      if (!(task.dueAt?.isAfter(now) == true || retryAt?.isAfter(now) == true))
        continue;
      await _cancelOccurrence(task.remoteId);
      await (_db.delete(
        _db.scheduledTasks,
      )..where((row) => row.remoteId.equals(task.remoteId))).go();
    }
  }

  static (Map<String, dynamic>, String?) _normalize(
    Map<String, dynamic> input,
  ) {
    final name = (input['name'] ?? '').toString().trim();
    if (name.isEmpty) return ({}, 'Informe o nome do hábito');
    final time = (input['time'] ?? '').toString();
    final match = RegExp(r'^(\d{1,2}):(\d{2})$').firstMatch(time);
    if (match == null ||
        int.parse(match[1]!) > 23 ||
        int.parse(match[2]!) > 59) {
      return ({}, 'Informe um horário válido');
    }
    final weekdays =
        (input['weekdays'] as List? ?? [])
            .whereType<num>()
            .map((d) => d.toInt())
            .where((d) => d >= 0 && d <= 6)
            .toSet()
            .toList()
          ..sort();
    if (weekdays.isEmpty) return ({}, 'Escolha pelo menos um dia');
    final mode = (input['alert_mode'] ?? 'none').toString();
    if (!modes.contains(mode)) return ({}, 'Escolha um modo de aviso válido');
    return (
      {
        'name': name,
        'time':
            '${int.parse(match[1]!).toString().padLeft(2, '0')}:${match[2]}',
        'weekdays': weekdays,
        'alert_mode': mode,
      },
      null,
    );
  }
}
