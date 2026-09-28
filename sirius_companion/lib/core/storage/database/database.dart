import 'dart:io';
import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;
import 'tables.dart';

part 'database.g.dart';

@DriftDatabase(tables: [SyncItems, Places, ScheduledTasks, Notes, PlaceVisits])
class AppDatabase extends _$AppDatabase {
  AppDatabase._() : super(_openConnection());

  /// Single shared instance. The app opens connections from multiple places
  /// (UI, services) and WorkManager spawns background isolates that also use
  /// this class — a per-call instance meant concurrent SQLite access with no
  /// busy timeout and led to lock contention. Never call close() on it.
  static final AppDatabase instance = AppDatabase._();

  factory AppDatabase() => instance;

  @override
  int get schemaVersion => 6;

  @override
  MigrationStrategy get migration => MigrationStrategy(
    onCreate: (Migrator m) async {
      await m.createAll();
    },
    onUpgrade: (Migrator m, int from, int to) async {
      if (from < 2) {
        await m.createTable(scheduledTasks);
      }
      if (from < 3) {
        await m.createTable(notes);
        await m.createTable(placeVisits);
      }
      if (from < 4) {
        await m.addColumn(scheduledTasks, scheduledTasks.startDate);
        await m.addColumn(scheduledTasks, scheduledTasks.endDate);
        await m.addColumn(scheduledTasks, scheduledTasks.isDateRange);
      }
      if (from < 5) {
        // Recreate scheduled_tasks table to make dueAt nullable
        // SQLite doesn't support ALTER COLUMN, so we recreate the table
        // Use snake_case column names to match existing table schema
        final executor = m.database.executor;
        await executor.runCustom('DROP TABLE IF EXISTS scheduled_tasks_new');
        await executor.runCustom('''
          CREATE TABLE scheduled_tasks_new (
            remote_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            notes TEXT,
            due_at INTEGER,  -- nullable
            status TEXT NOT NULL DEFAULT 'pending',
            source TEXT NOT NULL DEFAULT 'phone',
            alarm_scheduled INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            start_date INTEGER,
            end_date INTEGER,
            is_date_range INTEGER NOT NULL DEFAULT 0
          )
        ''');
        await executor.runCustom('''
          INSERT INTO scheduled_tasks_new (
            remote_id, title, notes, due_at, status, source, 
            alarm_scheduled, created_at, updated_at, start_date, end_date, is_date_range
          )
          SELECT remote_id, title, notes, due_at, status, source,
            alarm_scheduled, created_at, updated_at, start_date, end_date, is_date_range
          FROM scheduled_tasks
        ''');
        await executor.runCustom('DROP TABLE scheduled_tasks');
        await executor.runCustom(
          'ALTER TABLE scheduled_tasks_new RENAME TO scheduled_tasks',
        );
        // Recreate index (use snake_case column names)
        await executor.runCustom('''
          CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_status_due_at 
          ON scheduled_tasks(status, due_at)
        ''');
        await executor.runCustom('''
          CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_date_range 
          ON scheduled_tasks(is_date_range, start_date, end_date) 
          WHERE is_date_range = 1 AND status IN ('pending','notified')
        ''');
      }
      if (from < 6) {
        await m.addColumn(notes, notes.classificationStatus);
        await m.addColumn(notes, notes.classificationError);
        await m.addColumn(notes, notes.syncedAt);
      }
    },
  );

  Future<void> deleteAll() async {
    await transaction(() async {
      await delete(syncItems).go();
      await delete(places).go();
      await delete(scheduledTasks).go();
      await delete(notes).go();
      await delete(placeVisits).go();
    });
  }
}

LazyDatabase _openConnection() {
  return LazyDatabase(() async {
    final dbFolder = await getApplicationDocumentsDirectory();
    final file = File(p.join(dbFolder.path, 'sirius_companion.sqlite'));
    return NativeDatabase(
      file,
      setup: (rawDb) {
        // Wait instead of failing immediately when another isolate/connection
        // holds the write lock, and allow concurrent readers via WAL.
        rawDb.execute('PRAGMA busy_timeout = 5000');
        rawDb.execute('PRAGMA journal_mode = WAL');
      },
    );
  });
}
