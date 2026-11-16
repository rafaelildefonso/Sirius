import 'dart:convert';

import 'package:drift/drift.dart';
import 'package:uuid/uuid.dart';

import '../../core/config/constants.dart';
import '../../core/storage/database/database.dart';
import '../../core/storage/repositories/sync_repository.dart';
import 'task_alarm_service.dart';

/// Local-first recurring task definitions and their scheduled occurrences.
class RecurringTaskService {
  RecurringTaskService._();

  static const weekdayShort = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];

  static final _db = AppDatabase();

  static Future<List<Map<String, dynamic>>> list() async {
    final definitions = await (_db.select(
      _db.recurringTaskDefinitions,
    )..orderBy([(row) => OrderingTerm.asc(row.createdAt)])).get();
    return definitions.map(_toMap).toList();
  }

  static Future<void> syncFromServer(
    List<Map<String, dynamic>> remoteItems,
  ) async {
    for (final remote in remoteItems) {
      final id = remote['id']?.toString() ?? '';
      if (id.isEmpty) continue;
      if (await _hasPendingChange(id)) continue;

      final local = await (_db.select(
        _db.recurringTaskDefinitions,
      )..where((row) => row.id.equals(id))).getSingleOrNull();
      final remoteUpdated = DateTime.tryParse(
        remote['updated_at']?.toString() ?? '',
      );
      if (local != null &&
          (remoteUpdated == null || !remoteUpdated.isAfter(local.updatedAt))) {
        continue;
      }

      final normalized = _normalize(remote);
      if (normalized['error'] != null) {
        throw FormatException(
          'Invalid recurring task received from PC ($id): ${normalized['error']}',
        );
      }
      final now = DateTime.now();
      final definition = normalized['payload'] as Map<String, dynamic>
        ..['id'] = id
        ..['source'] = 'mobile'
        ..['enabled'] = _asBool(remote['enabled'])
        ..['created_at'] =
            remote['created_at']?.toString() ??
            local?.createdAt.toIso8601String() ??
            now.toIso8601String()
        ..['updated_at'] =
            remoteUpdated?.toIso8601String() ?? now.toIso8601String();
      final createdAt =
          DateTime.tryParse(definition['created_at'] as String) ?? now;
      final updatedAt =
          DateTime.tryParse(definition['updated_at'] as String) ?? now;

      if (local == null) {
        await _db
            .into(_db.recurringTaskDefinitions)
            .insert(
              RecurringTaskDefinitionsCompanion.insert(
                id: id,
                payloadJson: jsonEncode(definition),
                enabled: Value(definition['enabled'] as bool),
                createdAt: createdAt,
                updatedAt: updatedAt,
              ),
            );
      } else {
        await (_db.update(
          _db.recurringTaskDefinitions,
        )..where((row) => row.id.equals(id))).write(
          RecurringTaskDefinitionsCompanion(
            payloadJson: Value(jsonEncode(definition)),
            enabled: Value(definition['enabled'] as bool),
            createdAt: Value(createdAt),
            updatedAt: Value(updatedAt),
          ),
        );
      }
      if (remote['source'] != 'mobile') {
        await _enqueueUpsert(definition);
      }
    }
    await generateDueOccurrences();
  }

  static Future<(Map<String, dynamic>?, String?)> create(
    Map<String, dynamic> payload,
  ) async {
    final normalized = _normalize(payload);
    if (normalized['error'] != null) {
      return (null, normalized['error'] as String);
    }

    final now = DateTime.now();
    final id = const Uuid().v4();
    final definition = normalized['payload'] as Map<String, dynamic>;
    definition['id'] = id;
    definition['source'] = 'mobile';
    definition['enabled'] = true;
    definition['created_at'] = now.toIso8601String();
    definition['updated_at'] = now.toIso8601String();

    await _db
        .into(_db.recurringTaskDefinitions)
        .insert(
          RecurringTaskDefinitionsCompanion.insert(
            id: id,
            payloadJson: jsonEncode(definition),
            createdAt: now,
            updatedAt: now,
          ),
        );
    await _enqueueUpsert(definition);
    await generateDueOccurrences();
    return (_withNext(definition), null);
  }

  static Future<bool> setEnabled(String id, bool enabled) =>
      update(id, {'enabled': enabled});

  static Future<bool> update(String id, Map<String, dynamic> changes) async {
    final row = await (_db.select(
      _db.recurringTaskDefinitions,
    )..where((item) => item.id.equals(id))).getSingleOrNull();
    if (row == null) return false;

    final current = Map<String, dynamic>.from(jsonDecode(row.payloadJson));
    final normalized = _normalize({...current, ...changes});
    if (normalized['error'] != null) return false;

    final now = DateTime.now();
    final next = normalized['payload'] as Map<String, dynamic>;
    next
      ..['id'] = id
      ..['source'] = 'mobile'
      ..['enabled'] = changes['enabled'] is bool
          ? changes['enabled']
          : row.enabled
      ..['created_at'] =
          current['created_at'] ?? row.createdAt.toIso8601String()
      ..['updated_at'] = now.toIso8601String();

    await (_db.update(
      _db.recurringTaskDefinitions,
    )..where((item) => item.id.equals(id))).write(
      RecurringTaskDefinitionsCompanion(
        payloadJson: Value(jsonEncode(next)),
        enabled: Value(next['enabled'] as bool),
        updatedAt: Value(now),
      ),
    );
    await _enqueueUpsert(next);
    await generateDueOccurrences();
    return true;
  }

  static Future<bool> delete(String id) async {
    final row = await (_db.select(
      _db.recurringTaskDefinitions,
    )..where((item) => item.id.equals(id))).getSingleOrNull();
    if (row == null) return false;

    final tasks =
        await (_db.select(_db.scheduledTasks)..where(
              (task) =>
                  task.recurrenceId.equals(id) &
                  (task.status.equals('pending') |
                      task.status.equals('notified')),
            ))
            .get();
    for (final task in tasks) {
      await TaskAlarmService.cancelAlarm(task.remoteId);
      await (_db.delete(
        _db.scheduledTasks,
      )..where((item) => item.remoteId.equals(task.remoteId))).go();
    }

    await (_db.delete(
      _db.recurringTaskDefinitions,
    )..where((item) => item.id.equals(id))).go();
    await SyncRepository(_db).enqueue(
      type: SyncItemType.recurringTaskDelete.value,
      payloadJson: jsonEncode({'id': id, 'source': 'mobile'}),
      clientId: const Uuid().v4(),
    );
    return true;
  }

  /// Materializes today's occurrence once. Safe to run on app start and from
  /// WorkManager: each occurrence has a stable local/server ID.
  static Future<void> generateDueOccurrences({DateTime? now}) async {
    final clock = now ?? DateTime.now();
    final today = DateTime(clock.year, clock.month, clock.day);
    final definitions = await (_db.select(
      _db.recurringTaskDefinitions,
    )..where((row) => row.enabled.equals(true))).get();

    for (final row in definitions) {
      final definition = _toMap(row);
      final occurrenceDate = _latestGenerationDay(definition, today);
      if (occurrenceDate == null) continue;

      final occurrenceKey = _dateKey(occurrenceDate);
      final remoteId = '${row.id}_$occurrenceKey';

      final time = definition['time_of_day']?.toString();
      DateTime? dueAt;
      if (time != null && time.isNotEmpty) {
        final parts = time.split(':');
        dueAt = DateTime(
          occurrenceDate.year,
          occurrenceDate.month,
          occurrenceDate.day,
          int.parse(parts[0]),
          int.parse(parts[1]),
        );
      }

      final periodDays = (definition['period_days'] as num?)?.toInt() ?? 0;
      final isDateRange = periodDays > 0;
      final previous =
          await (_db.select(_db.scheduledTasks)..where(
                (task) =>
                    task.recurrenceId.equals(row.id) &
                    (task.status.equals('pending') |
                        task.status.equals('notified')),
              ))
              .get();
      for (final task in previous) {
        if (task.remoteId == remoteId) continue;
        await TaskAlarmService.cancelAlarm(task.remoteId);
        await (_db.delete(
          _db.scheduledTasks,
        )..where((item) => item.remoteId.equals(task.remoteId))).go();
      }

      final existing = await (_db.select(
        _db.scheduledTasks,
      )..where((task) => task.remoteId.equals(remoteId))).getSingleOrNull();
      if (existing != null) continue;
      if (dueAt != null &&
          dueAt.isBefore(clock.subtract(const Duration(hours: 2)))) {
        await (_db.update(
          _db.recurringTaskDefinitions,
        )..where((item) => item.id.equals(row.id))).write(
          RecurringTaskDefinitionsCompanion(lastGeneratedDate: Value(today)),
        );
        continue;
      }

      await TaskAlarmService.createQuickTask(
        definition['title'].toString(),
        dueAt: isDateRange ? null : dueAt,
        startDate: isDateRange ? occurrenceDate : null,
        endDate: isDateRange
            ? occurrenceDate.add(Duration(days: periodDays - 1))
            : null,
        isDateRange: isDateRange,
        notes: definition['notes']?.toString(),
        siriusCallEnabled:
            !isDateRange && definition['sirius_call_enabled'] == true,
        remoteId: remoteId,
        recurrenceId: row.id,
        requestPermissions: false,
      );
      await (_db.update(
        _db.recurringTaskDefinitions,
      )..where((item) => item.id.equals(row.id))).write(
        RecurringTaskDefinitionsCompanion(lastGeneratedDate: Value(today)),
      );
    }
  }

  static String describe(Map<String, dynamic> rec) {
    final type = (rec['recurrence_type'] ?? '').toString();
    final periodDays = (rec['period_days'] as num?)?.toInt() ?? 0;
    final timeOfDay = (rec['time_of_day'] ?? '').toString();

    String schedule;
    switch (type) {
      case 'daily':
        schedule = 'Todos os dias';
        break;
      case 'weekly':
        final weekdays =
            (rec['weekdays'] as List? ?? [])
                .whereType<num>()
                .map((e) => e.toInt())
                .where((day) => day >= 0 && day < weekdayShort.length)
                .toList()
              ..sort();
        schedule = weekdays.isEmpty
            ? 'Toda semana'
            : 'Toda ${weekdays.map((day) => weekdayShort[day]).join(', ')}';
        break;
      case 'interval':
        final interval = (rec['interval_days'] as num?)?.toInt() ?? 1;
        schedule = 'A cada $interval dia${interval == 1 ? '' : 's'}';
        break;
      case 'monthly':
        final monthDay = (rec['month_day'] as num?)?.toInt() ?? 1;
        schedule = 'Todo dia $monthDay do mês';
        break;
      default:
        schedule = type;
    }

    if (periodDays > 0) {
      return '$schedule — período de $periodDays '
          'dia${periodDays == 1 ? '' : 's'}';
    }
    return timeOfDay.isEmpty ? schedule : '$schedule às $timeOfDay';
  }

  static String? nextLabel(Map<String, dynamic> rec) {
    final now = DateTime.now();
    var from = _dateOnly(now);
    final time = rec['time_of_day']?.toString();
    if ((rec['period_days'] as num?)?.toInt() == 0 &&
        time != null &&
        time.isNotEmpty) {
      final parts = time.split(':');
      final todayAt = DateTime(
        now.year,
        now.month,
        now.day,
        int.parse(parts[0]),
        int.parse(parts[1]),
      );
      if (todayAt.isBefore(now)) from = from.add(const Duration(days: 1));
    }
    final next = _nextGenerationDay(rec, from);
    if (next == null) return rec['enabled'] == true ? null : '—';
    final diff = next.difference(_dateOnly(now)).inDays;
    if (diff == 0) return 'hoje';
    if (diff == 1) return 'amanhã';
    return '${next.day.toString().padLeft(2, '0')}/'
        '${next.month.toString().padLeft(2, '0')}';
  }

  static DateTime? nextOccurrence(
    Map<String, dynamic> definition,
    DateTime from,
  ) => _nextGenerationDay(definition, _dateOnly(from));

  static Map<String, dynamic> _toMap(RecurringTaskDefinition row) {
    final result = Map<String, dynamic>.from(jsonDecode(row.payloadJson));
    result
      ..['id'] = row.id
      ..['enabled'] = row.enabled
      ..['created_at'] = row.createdAt.toIso8601String()
      ..['updated_at'] = row.updatedAt.toIso8601String()
      ..['last_generated_date'] = row.lastGeneratedDate?.toIso8601String()
      ..['next_occurrence'] = _nextGenerationDay(
        result,
        DateTime.now(),
      )?.toIso8601String();
    return result;
  }

  static Map<String, dynamic> _withNext(Map<String, dynamic> definition) => {
    ...definition,
    'next_occurrence': _nextGenerationDay(
      definition,
      DateTime.now(),
    )?.toIso8601String(),
  };

  static Map<String, dynamic> _normalize(Map<String, dynamic> input) {
    final title = (input['title'] ?? input['message'] ?? '').toString().trim();
    if (title.isEmpty) return {'error': 'Informe um título'};

    final type = (input['recurrence_type'] ?? input['type'] ?? '')
        .toString()
        .trim()
        .toLowerCase();
    const supported = {'daily', 'weekly', 'interval', 'monthly'};
    if (!supported.contains(type)) {
      return {'error': 'Tipo de recorrência inválido'};
    }

    final weekdays =
        (input['weekdays'] as List? ?? [])
            .whereType<num>()
            .map((day) => day.toInt())
            .where((day) => day >= 0 && day <= 6)
            .toSet()
            .toList()
          ..sort();
    if (type == 'weekly' && weekdays.isEmpty) {
      return {'error': 'Escolha pelo menos um dia da semana'};
    }

    final interval = int.tryParse('${input['interval_days'] ?? 0}');
    if (type == 'interval' && (interval == null || interval < 1)) {
      return {'error': 'O intervalo deve ser de pelo menos 1 dia'};
    }
    final monthDay = int.tryParse('${input['month_day'] ?? 0}');
    if (type == 'monthly' &&
        (monthDay == null || monthDay < 1 || monthDay > 31)) {
      return {'error': 'O dia do mês deve estar entre 1 e 31'};
    }

    final periodDays = int.tryParse('${input['period_days'] ?? 0}') ?? 0;
    if (periodDays < 0 || periodDays > 365) {
      return {'error': 'O período deve estar entre 0 e 365 dias'};
    }
    final rawTime = input['time_of_day']?.toString();
    final time = periodDays > 0 ? null : _normalizeTime(rawTime ?? '09:00');
    if (periodDays == 0 && time == null) {
      return {'error': 'Horário inválido'};
    }

    final startFrom =
        _parseDate(input['start_from']) ??
        _parseDate(input['created_at']) ??
        _dateOnly(DateTime.now());
    final endDate = _parseDate(input['end_date']);
    if (input['start_from'] != null &&
        _parseDate(input['start_from']) == null) {
      return {'error': 'Data inicial inválida'};
    }
    if (input['end_date'] != null && endDate == null) {
      return {'error': 'Data final inválida'};
    }
    if (endDate != null && endDate.isBefore(startFrom)) {
      return {'error': 'A data final não pode ser anterior à inicial'};
    }
    final endDateKey = endDate == null ? null : _isoDateKey(endDate);

    return {
      'payload': <String, dynamic>{
        'title': title,
        'notes': (input['notes'] ?? '').toString().trim(),
        'recurrence_type': type,
        if (type == 'weekly') 'weekdays': weekdays,
        if (type == 'interval') 'interval_days': interval,
        if (type == 'monthly') 'month_day': monthDay,
        'period_days': periodDays,
        'sirius_call_enabled': _asBool(input['sirius_call_enabled']),
        'time_of_day': ?time,
        'start_from': _isoDateKey(startFrom),
        'end_date': ?endDateKey,
      },
    };
  }

  static String? _normalizeTime(String value) {
    final match = RegExp(r'^(\d{1,2}):(\d{1,2})$').firstMatch(value.trim());
    if (match == null) return null;
    final hour = int.parse(match.group(1)!);
    final minute = int.parse(match.group(2)!);
    if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return null;
    return '${hour.toString().padLeft(2, '0')}:'
        '${minute.toString().padLeft(2, '0')}';
  }

  static bool _asBool(dynamic value) =>
      value == true || value == 1 || value?.toString() == '1';

  static DateTime? _parseDate(dynamic value) {
    if (value == null || value.toString().isEmpty) return null;
    final parsed = DateTime.tryParse(value.toString());
    return parsed == null ? null : _dateOnly(parsed);
  }

  static DateTime _dateOnly(DateTime date) =>
      DateTime(date.year, date.month, date.day);

  static String _dateKey(DateTime date) =>
      '${date.year.toString().padLeft(4, '0')}'
      '${date.month.toString().padLeft(2, '0')}'
      '${date.day.toString().padLeft(2, '0')}';

  static String _isoDateKey(DateTime date) =>
      '${date.year.toString().padLeft(4, '0')}-'
      '${date.month.toString().padLeft(2, '0')}-'
      '${date.day.toString().padLeft(2, '0')}';

  static DateTime? _nextGenerationDay(
    Map<String, dynamic> definition,
    DateTime from,
  ) {
    final start = _parseDate(definition['start_from']);
    final first = start != null && start.isAfter(_dateOnly(from))
        ? start
        : _dateOnly(from);
    for (var offset = 0; offset < 3660; offset++) {
      final candidate = first.add(Duration(days: offset));
      final end = _parseDate(definition['end_date']);
      if (end != null && candidate.isAfter(end)) return null;
      if (_isGenerationDay(definition, candidate)) return candidate;
    }
    return null;
  }

  static DateTime? _latestGenerationDay(
    Map<String, dynamic> definition,
    DateTime through,
  ) {
    final start =
        _parseDate(definition['start_from']) ??
        _parseDate(definition['created_at']) ??
        through;
    if (start.isAfter(through)) return null;
    final end = _parseDate(definition['end_date']);
    final lastDay = end != null && end.isBefore(through) ? end : through;
    for (var offset = 0; offset <= 3660; offset++) {
      final candidate = lastDay.subtract(Duration(days: offset));
      if (candidate.isBefore(start)) return null;
      if (_isGenerationDay(definition, candidate)) return candidate;
    }
    return null;
  }

  static bool _isGenerationDay(Map<String, dynamic> definition, DateTime day) {
    switch (definition['recurrence_type']) {
      case 'daily':
        return true;
      case 'weekly':
        final weekdays = (definition['weekdays'] as List? ?? [])
            .whereType<num>()
            .map((value) => value.toInt());
        return weekdays.contains(day.weekday - 1);
      case 'interval':
        final interval = (definition['interval_days'] as num?)?.toInt() ?? 1;
        final anchor =
            _parseDate(definition['start_from']) ??
            _parseDate(definition['created_at']);
        return anchor != null &&
            day.difference(anchor).inDays >= 0 &&
            day.difference(anchor).inDays % interval == 0;
      case 'monthly':
        final requested = (definition['month_day'] as num?)?.toInt() ?? 1;
        final lastDay = DateTime(day.year, day.month + 1, 0).day;
        return day.day == (requested > lastDay ? lastDay : requested);
      default:
        return false;
    }
  }

  static Future<void> _enqueueUpsert(Map<String, dynamic> definition) async {
    await SyncRepository(_db).enqueue(
      type: SyncItemType.recurringTaskUpsert.value,
      payloadJson: jsonEncode(definition),
      clientId: const Uuid().v4(),
    );
  }

  static Future<bool> _hasPendingChange(String id) async {
    final pending =
        await (_db.select(_db.syncItems)..where(
              (item) =>
                  item.syncedAt.isNull() &
                  item.type.isIn([
                    SyncItemType.recurringTaskUpsert.value,
                    SyncItemType.recurringTaskDelete.value,
                  ]),
            ))
            .get();
    for (final item in pending) {
      try {
        final payload = jsonDecode(item.payloadJson) as Map<String, dynamic>;
        if (payload['id']?.toString() == id) return true;
      } on FormatException {
        continue;
      }
    }
    return false;
  }
}
