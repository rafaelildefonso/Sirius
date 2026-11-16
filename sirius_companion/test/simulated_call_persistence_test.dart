import 'dart:io';

import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sirius_companion/core/storage/database/database.dart';

void main() {
  test(
    'call preference and pending retry survive reopening local storage',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'sirius-call-test-',
      );
      addTearDown(() async {
        if (await directory.exists()) await directory.delete(recursive: true);
      });
      final file = File(
        '${directory.path}${Platform.pathSeparator}tasks.sqlite',
      );
      var db = AppDatabase.forTesting(NativeDatabase(file));
      final now = DateTime.now();

      await db
          .into(db.scheduledTasks)
          .insert(
            ScheduledTasksCompanion.insert(
              remoteId: 'task-1',
              title: 'Dentista',
              createdAt: now,
              updatedAt: now,
            ),
          );
      await db.customStatement(
        'UPDATE scheduled_tasks SET sirius_call_enabled = 1, sirius_call_refusals = 2, sirius_call_retry_at = ? WHERE remote_id = ?',
        [now.add(const Duration(minutes: 5)).toIso8601String(), 'task-1'],
      );
      await db.close();

      db = AppDatabase.forTesting(NativeDatabase(file));
      final row = await db
          .customSelect(
            'SELECT sirius_call_enabled, sirius_call_refusals, sirius_call_retry_at FROM scheduled_tasks WHERE remote_id = ?',
            variables: [Variable('task-1')],
          )
          .getSingle();

      expect(row.data['sirius_call_enabled'], 1);
      expect(row.data['sirius_call_refusals'], 2);
      expect(
        DateTime.parse(row.data['sirius_call_retry_at'] as String),
        now.add(const Duration(minutes: 5)),
      );

      await db.close();
    },
  );
}
