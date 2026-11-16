import 'dart:io';

import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sirius_companion/core/storage/database/database.dart';
import 'package:sirius_companion/features/tasks/routine_service.dart';
import 'package:sirius_companion/features/tasks/task_alarm_service.dart';

void main() {
  group('Routine weekday and local-time rules', () {
    final sunday = DateTime(2026, 11, 15);
    test('matches one, several, and every selected weekday', () {
      expect(RoutineService.isScheduledOn([0], sunday), isTrue);
      expect(RoutineService.isScheduledOn([1, 3, 0], sunday), isTrue);
      expect(
        RoutineService.isScheduledOn(List.generate(7, (i) => i), sunday),
        isTrue,
      );
      expect(RoutineService.isScheduledOn([1, 2, 3, 4, 5, 6], sunday), isFalse);
    });

    test('builds occurrence at local wall-clock time', () {
      final due = RoutineService.occurrenceDateTime(sunday, '08:35');
      expect(due.year, sunday.year);
      expect(due.month, sunday.month);
      expect(due.day, sunday.day);
      expect(due.hour, 8);
      expect(due.minute, 35);
      expect(due.isUtc, isFalse);
    });

    test('exposes exactly the four routine alert modes', () {
      expect(RoutineService.modes, {'none', 'notification', 'alarm', 'call'});
    });

    test('each date gets an independent, stable occurrence alarm id', () {
      final first = RoutineService.occurrenceId('habit-a', sunday);
      final next = RoutineService.occurrenceId(
        'habit-a',
        sunday.add(const Duration(days: 1)),
      );
      expect(first, 'habit-a_20261115');
      expect(next, 'habit-a_20261116');
      expect(
        TaskAlarmService.notificationId(first),
        TaskAlarmService.notificationId(first),
      );
      expect(
        TaskAlarmService.notificationId(first),
        isNot(TaskAlarmService.notificationId(next)),
      );
    });
  });

  test('schema upgrade from v9 preserves tasks and survives reopening', () async {
    final dir = await Directory.systemTemp.createTemp('sirius-routine-db-');
    addTearDown(() async => dir.delete(recursive: true));
    final file = File('${dir.path}${Platform.pathSeparator}routine.sqlite');
    var db = AppDatabase.forTesting(NativeDatabase(file));
    final now = DateTime.now();
    await db
        .into(db.scheduledTasks)
        .insert(
          ScheduledTasksCompanion.insert(
            remoteId: 'old-task',
            title: 'Compromisso existente',
            createdAt: now,
            updatedAt: now,
          ),
        );
    await db.customStatement('DROP TABLE routine_definitions');
    await db.customStatement(
      'ALTER TABLE scheduled_tasks DROP COLUMN routine_alert_mode',
    );
    await db.customStatement('PRAGMA user_version = 9');
    await db.close();

    db = AppDatabase.forTesting(NativeDatabase(file));
    final row = await (db.select(
      db.scheduledTasks,
    )..where((task) => task.remoteId.equals('old-task'))).getSingle();
    expect(row.title, 'Compromisso existente');
    expect(
      await db
          .customSelect(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='routine_definitions'",
          )
          .getSingleOrNull(),
      isNotNull,
    );
    final columns = await db
        .customSelect('PRAGMA table_info(scheduled_tasks)')
        .get();
    expect(
      columns.map((row) => row.data['name']),
      contains('routine_alert_mode'),
    );
    await db.close();

    db = AppDatabase.forTesting(NativeDatabase(file));
    expect(
      (await (db.select(
        db.scheduledTasks,
      )..where((task) => task.remoteId.equals('old-task'))).getSingle()).title,
      'Compromisso existente',
    );
    await db.close();
  });

  test(
    'modes, completion, edits, pause, delete, and history are occurrence-scoped',
    () async {
      final db = AppDatabase.forTesting(NativeDatabase.memory());
      addTearDown(db.close);
      final seenModes = <String>{};
      final cancelled = <String>[];
      RoutineService.configureForTesting(
        database: db,
        createOccurrence:
            ({
              required remoteId,
              required title,
              required dueAt,
              required routineId,
              required alertMode,
            }) async {
              seenModes.add(alertMode);
              final existing =
                  await (db.select(db.scheduledTasks)
                        ..where((row) => row.remoteId.equals(remoteId)))
                      .getSingleOrNull();
              if (existing != null) return;
              await db
                  .into(db.scheduledTasks)
                  .insert(
                    ScheduledTasksCompanion.insert(
                      remoteId: remoteId,
                      recurrenceId: Value(routineId),
                      title: title,
                      dueAt: Value(dueAt),
                      source: const Value('routine'),
                      routineAlertMode: Value(alertMode),
                      createdAt: DateTime.now(),
                      updatedAt: DateTime.now(),
                    ),
                  );
            },
        cancelOccurrence: (id) async {
          cancelled.add(id);
        },
        completeOccurrence: (id) async {
          await (db.update(db.scheduledTasks)
                ..where((row) => row.remoteId.equals(id)))
              .write(const ScheduledTasksCompanion(status: Value('done')));
        },
      );

      for (final mode in RoutineService.modes) {
        final (_, error) = await RoutineService.create({
          'name': 'Hábito $mode',
          'time': '23:59',
          'weekdays': List.generate(7, (i) => i),
          'alert_mode': mode,
        });
        expect(error, isNull);
      }
      expect(seenModes, RoutineService.modes);

      final routine = (await RoutineService.list()).firstWhere(
        (item) => item['alert_mode'] == 'none',
      );
      final rows =
          await (db.select(db.scheduledTasks)..where(
                (row) => row.recurrenceId.equals(routine['id'] as String),
              ))
              .get();
      final upcoming = rows.firstWhere(
        (row) => row.dueAt!.isAfter(DateTime.now()),
      );
      await RoutineService.complete(upcoming.remoteId);
      final nextDate = rows.firstWhere(
        (row) => row.dueAt!.isAfter(upcoming.dueAt!),
      );
      expect(
        (await (db.select(db.scheduledTasks)
                  ..where((row) => row.remoteId.equals(upcoming.remoteId)))
                .getSingle())
            .status,
        'done',
      );
      expect(
        (await (db.select(db.scheduledTasks)
                  ..where((row) => row.remoteId.equals(nextDate.remoteId)))
                .getSingle())
            .status,
        'pending',
      );

      await RoutineService.update(routine['id'] as String, {
        'name': 'Hábito alterado',
        'time': '22:30',
      });
      expect(
        (await (db.select(db.scheduledTasks)
                  ..where((row) => row.remoteId.equals(upcoming.remoteId)))
                .getSingle())
            .title,
        'Hábito none',
      );
      expect(cancelled, isNotEmpty);
      await RoutineService.setEnabled(routine['id'] as String, false);
      expect(
        (await (db.select(db.scheduledTasks)
                  ..where((row) => row.remoteId.equals(upcoming.remoteId)))
                .getSingle())
            .status,
        'done',
      );
      await RoutineService.delete(routine['id'] as String);
      expect(
        (await (db.select(db.scheduledTasks)
                  ..where((row) => row.remoteId.equals(upcoming.remoteId)))
                .getSingle())
            .status,
        'done',
      );
    },
  );
}
