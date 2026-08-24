import 'package:drift/drift.dart';
import '../../config/constants.dart';
import '../database/database.dart';
import '../models/sync_item.dart' as model;

class SyncRepository {
  final AppDatabase db;
  SyncRepository(this.db);

  Future<int> enqueue({
    required String type,
    required String payloadJson,
    required String clientId,
  }) async {
    return await db.into(db.syncItems).insert(
      SyncItemsCompanion.insert(
        type: type,
        payloadJson: payloadJson,
        clientId: clientId,
        createdAt: DateTime.now(),
      ),
    );
  }

  Future<void> enqueueBatch(List<SyncItemsCompanion> items) async {
    await db.batch((batch) {
      batch.insertAll(db.syncItems, items);
    });
  }

  Future<List<model.SyncItem>> getPending({
    int limit = 100,
    int maxRetries = AppConstants.deadLetterRetries,
  }) async {
    final driftItems = await (db.select(db.syncItems)
          ..where((tbl) =>
              tbl.syncedAt.isNull() &
              tbl.retryCount.isSmallerOrEqualValue(maxRetries))
          ..orderBy([(tbl) => OrderingTerm.asc(tbl.createdAt)])
          ..limit(limit))
        .get();
    return driftItems.map(_toModel).toList();
  }

  Future<List<model.SyncItem>> getPendingByType(String type, {int limit = 100}) async {
    final driftItems = await (db.select(db.syncItems)
          ..where((tbl) => tbl.syncedAt.isNull() & tbl.type.equals(type))
          ..orderBy([(tbl) => OrderingTerm.asc(tbl.createdAt)])
          ..limit(limit))
        .get();
    return driftItems.map(_toModel).toList();
  }

  Future<void> markSynced(List<String> clientIds) async {
    await db.transaction(() async {
      for (final clientId in clientIds) {
        await (db.update(db.syncItems)
              ..where((tbl) => tbl.clientId.equals(clientId)))
            .write(SyncItemsCompanion(
              syncedAt: Value(DateTime.now()),
            ));
      }
    });
  }

  Future<void> incrementRetry(String clientId, String error) async {
    final item = await (db.select(db.syncItems)
          ..where((tbl) => tbl.clientId.equals(clientId)))
        .getSingleOrNull();
    if (item != null) {
      await (db.update(db.syncItems)
            ..where((tbl) => tbl.clientId.equals(clientId)))
        .write(SyncItemsCompanion(
          retryCount: Value(item.retryCount + 1),
          lastError: Value(error),
        ));
    }
  }

  Future<int> getPendingCount() async {
    final countExp = db.syncItems.id.count();
    final row = await (db.selectOnly(db.syncItems)
          ..addColumns([countExp])
          ..where(db.syncItems.syncedAt.isNull()))
        .getSingle();
    return row.read(countExp) ?? 0;
  }

  Future<int> getFailedCount({int? maxRetries}) async {
    final effectiveMax = maxRetries ?? AppConstants.deadLetterRetries;
    final countExp = db.syncItems.id.count();
    final row = await (db.selectOnly(db.syncItems)
          ..addColumns([countExp])
          ..where(db.syncItems.syncedAt.isNull() &
              db.syncItems.retryCount.isBiggerThanValue(effectiveMax)))
        .getSingle();
    return row.read(countExp) ?? 0;
  }

  Future<void> clearSynced({Duration olderThan = const Duration(days: 7)}) async {
    final cutoff = DateTime.now().subtract(olderThan);
    await (db.delete(db.syncItems)
          ..where((tbl) => tbl.syncedAt.isNotNull() & tbl.syncedAt.isSmallerThanValue(cutoff)))
        .go();
  }

  model.SyncItem _toModel(SyncItem driftItem) {
    return model.SyncItem(
      id: driftItem.id,
      type: driftItem.type,
      payloadJson: driftItem.payloadJson,
      createdAt: driftItem.createdAt,
      syncedAt: driftItem.syncedAt,
      retryCount: driftItem.retryCount,
      lastError: driftItem.lastError,
      clientId: driftItem.clientId,
    );
  }
}