import 'package:drift/drift.dart';
import '../database/database.dart';
import '../models/place.dart' as model;

class PlaceRepository {
  final AppDatabase db;
  PlaceRepository(this.db);

  Future<int> save(model.Place place) async {
    return await db.into(db.places).insert(
      PlacesCompanion.insert(
        uuid: place.uuid,
        name: place.name,
        latitude: place.latitude,
        longitude: place.longitude,
        radiusMeters: Value(place.radiusMeters),
        isActive: Value(place.isActive),
        createdAt: place.createdAt,
        lastTriggeredAt: Value(place.lastTriggeredAt),
        triggerCount: Value(place.triggerCount),
      ),
    );
  }

  Future<void> saveAll(List<model.Place> places) async {
    await db.batch((batch) {
      batch.insertAll(db.places, places.map((p) => PlacesCompanion.insert(
        uuid: p.uuid,
        name: p.name,
        latitude: p.latitude,
        longitude: p.longitude,
        radiusMeters: Value(p.radiusMeters),
        isActive: Value(p.isActive),
        createdAt: p.createdAt,
        lastTriggeredAt: Value(p.lastTriggeredAt),
        triggerCount: Value(p.triggerCount),
      )).toList());
    });
  }

  Future<model.Place?> getById(int id) async {
    final driftPlace = await (db.select(db.places)..where((tbl) => tbl.id.equals(id))).getSingleOrNull();
    return driftPlace != null ? _toModel(driftPlace) : null;
  }

  Future<model.Place?> getByUuid(String uuid) async {
    final driftPlace = await (db.select(db.places)..where((tbl) => tbl.uuid.equals(uuid))).getSingleOrNull();
    return driftPlace != null ? _toModel(driftPlace) : null;
  }

  Future<List<model.Place>> getAll({bool activeOnly = true}) async {
    final query = db.select(db.places);
    if (activeOnly) {
      query.where((tbl) => tbl.isActive.equals(true));
    }
    final driftPlaces = await query.get();
    return driftPlaces.map(_toModel).toList();
  }

  Future<List<model.Place>> getActiveGeofences() async {
    final driftPlaces = await (db.select(db.places)..where((tbl) => tbl.isActive.equals(true))).get();
    return driftPlaces.map(_toModel).toList();
  }

  Future<void> delete(String uuid) async {
    await (db.delete(db.places)..where((tbl) => tbl.uuid.equals(uuid))).go();
  }

  Future<void> updateTrigger(String uuid) async {
    final driftPlace = await (db.select(db.places)..where((tbl) => tbl.uuid.equals(uuid))).getSingleOrNull();
    if (driftPlace != null) {
      await (db.update(db.places)..where((tbl) => tbl.uuid.equals(uuid)))
          .write(PlacesCompanion(
        lastTriggeredAt: Value(DateTime.now()),
        triggerCount: Value(driftPlace.triggerCount + 1),
      ));
    }
  }

  Future<void> setActive(String uuid, bool active) async {
    await (db.update(db.places)..where((tbl) => tbl.uuid.equals(uuid)))
        .write(PlacesCompanion(isActive: Value(active)));
  }

  model.Place _toModel(Place driftPlace) {
    return model.Place(
      id: driftPlace.id,
      uuid: driftPlace.uuid,
      name: driftPlace.name,
      latitude: driftPlace.latitude,
      longitude: driftPlace.longitude,
      radiusMeters: driftPlace.radiusMeters,
      isActive: driftPlace.isActive,
      createdAt: driftPlace.createdAt,
      lastTriggeredAt: driftPlace.lastTriggeredAt,
      triggerCount: driftPlace.triggerCount,
    );
  }
}