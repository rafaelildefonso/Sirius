import 'dart:io';
import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;
import 'tables.dart';

part 'database.g.dart';

@DriftDatabase(tables: [SyncItems, Places, ScheduledTasks])
class AppDatabase extends _$AppDatabase {
  AppDatabase._() : super(_openConnection());

  /// Single shared instance. The app opens connections from multiple places
  /// (UI, services) and WorkManager spawns background isolates that also use
  /// this class — a per-call instance meant concurrent SQLite access with no
  /// busy timeout and led to lock contention. Never call close() on it.
  static final AppDatabase instance = AppDatabase._();

  factory AppDatabase() => instance;

  @override
  int get schemaVersion => 2;

  @override
  MigrationStrategy get migration => MigrationStrategy(
    onCreate: (Migrator m) async {
      await m.createAll();
    },
    onUpgrade: (Migrator m, int from, int to) async {
      if (from < 2) {
        await m.createTable(scheduledTasks);
      }
    },
  );

  Future<void> deleteAll() async {
    await transaction(() async {
      await delete(syncItems).go();
      await delete(places).go();
      await delete(scheduledTasks).go();
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
