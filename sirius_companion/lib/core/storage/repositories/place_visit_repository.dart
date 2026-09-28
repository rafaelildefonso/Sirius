import 'package:drift/drift.dart';
import 'package:uuid/uuid.dart';
import '../database/database.dart';

class PlaceVisitRepository {
  final AppDatabase _db;

  PlaceVisitRepository(this._db);

  Future<int> startVisit({
    required String placeId,
    required String placeName,
    required DateTime enteredAt,
    bool confirmed = false,
  }) async {
    return await _db.into(_db.placeVisits).insert(
      PlaceVisitsCompanion.insert(
        uuid: const Uuid().v4(),
        placeId: placeId,
        placeName: placeName,
        enteredAt: enteredAt,
        confirmed: Value(confirmed),
        createdAt: DateTime.now(),
      ),
    );
  }

  Future<void> endVisit({
    required int id,
    required DateTime exitedAt,
  }) async {
    final visit = await (_db.select(_db.placeVisits)
          ..where((tbl) => tbl.id.equals(id)))
        .getSingleOrNull();
    if (visit == null) return;

    final duration = exitedAt.difference(visit.enteredAt).inSeconds;
    await (_db.update(_db.placeVisits)..where((tbl) => tbl.id.equals(id))).write(
      PlaceVisitsCompanion(
        exitedAt: Value(exitedAt),
        durationSeconds: Value(duration),
      ),
    );
  }

  Future<void> endVisitByUuid({
    required String uuid,
    required DateTime exitedAt,
  }) async {
    final visit = await (_db.select(_db.placeVisits)
          ..where((tbl) => tbl.uuid.equals(uuid)))
        .getSingleOrNull();
    if (visit == null) return;

    final duration = exitedAt.difference(visit.enteredAt).inSeconds;
    await (_db.update(_db.placeVisits)..where((tbl) => tbl.uuid.equals(uuid))).write(
      PlaceVisitsCompanion(
        exitedAt: Value(exitedAt),
        durationSeconds: Value(duration),
      ),
    );
  }

  Future<void> delete(int id) async {
    await (_db.delete(_db.placeVisits)..where((tbl) => tbl.id.equals(id))).go();
  }

  Future<void> deleteByUuid(String uuid) async {
    await (_db.delete(_db.placeVisits)..where((tbl) => tbl.uuid.equals(uuid))).go();
  }

  Future<PlaceVisit?> getActiveVisit(String placeId) async {
    return await (_db.select(_db.placeVisits)
          ..where((tbl) => tbl.placeId.equals(placeId) & tbl.exitedAt.isNull())
          ..limit(1))
        .getSingleOrNull();
  }

  Future<PlaceVisit?> getActiveVisitByUuid(String placeUuid) async {
    return await (_db.select(_db.placeVisits)
          ..where((tbl) => tbl.placeId.equals(placeUuid) & tbl.exitedAt.isNull())
          ..limit(1))
        .getSingleOrNull();
  }

  Future<List<PlaceVisit>> getAll() async {
    return await (_db.select(_db.placeVisits)
          ..orderBy([(t) => OrderingTerm.desc(t.enteredAt)])
          ..limit(200))
        .get();
  }

  Future<List<PlaceVisit>> getPendingSync() async {
    return await (_db.select(_db.placeVisits)
          ..where((tbl) => tbl.syncStatus.equals('pending'))
          ..orderBy([(t) => OrderingTerm.asc(t.enteredAt)]))
        .get();
  }

  Future<int> getPendingSyncCount() async {
    final countExp = _db.placeVisits.id.count();
    final row = await (_db.selectOnly(_db.placeVisits)
          ..addColumns([countExp])
          ..where(_db.placeVisits.syncStatus.equals('pending')))
        .getSingle();
    return row.read(countExp) ?? 0;
  }

  Future<void> markSynced(String uuid) async {
    await (_db.update(_db.placeVisits)..where((tbl) => tbl.uuid.equals(uuid))).write(
      const PlaceVisitsCompanion(syncStatus: Value('synced')),
    );
  }

  Future<void> setSyncStatus(String uuid, String status) async {
    await (_db.update(_db.placeVisits)..where((tbl) => tbl.uuid.equals(uuid))).write(
      PlaceVisitsCompanion(
        syncStatus: Value(status),
        createdAt: Value(DateTime.now()),
      ),
    );
  }

  Future<int> getVisitCount(String placeId) async {
    final query = _db.select(_db.placeVisits)
      ..where((tbl) => tbl.placeId.equals(placeId));
    final visits = await query.get();
    return visits.length;
  }

  Future<Duration> getTotalDuration(String placeId) async {
    final query = _db.select(_db.placeVisits)
      ..where((tbl) => tbl.placeId.equals(placeId) & tbl.exitedAt.isNotNull());
    final visits = await query.get();
    int totalSeconds = 0;
    for (final v in visits) {
      totalSeconds += v.durationSeconds;
    }
    return Duration(seconds: totalSeconds);
  }

  Stream<List<PlaceVisit>> watchAll() {
    return (_db.select(_db.placeVisits)
          ..orderBy([(t) => OrderingTerm.desc(t.enteredAt)]))
        .watch();
  }
}
