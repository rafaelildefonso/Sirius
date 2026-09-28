import 'dart:convert';
import 'dart:io';
import 'package:drift/drift.dart';
import 'package:uuid/uuid.dart';
import '../database/database.dart';

class NoteRepository {
  final AppDatabase _db;

  NoteRepository(this._db);

  Future<int> create({
    required String title,
    required String content,
    required String category,
    String? aiSummary,
    String? aiTags,
    List<String>? attachmentPaths,
    int totalAttachmentBytes = 0,
  }) async {
    final now = DateTime.now();
    return await _db
        .into(_db.notes)
        .insert(
          NotesCompanion.insert(
            uuid: const Uuid().v4(),
            content: content,
            category: category,
            title: Value(title),
            aiSummary: Value(aiSummary),
            aiTags: Value(aiTags),
            classificationStatus: const Value('pending'),
            attachmentPaths: Value(
              attachmentPaths != null ? jsonEncode(attachmentPaths) : null,
            ),
            totalAttachmentBytes: Value(totalAttachmentBytes),
            createdAt: now,
            updatedAt: now,
          ),
        );
  }

  Future<void> updateNote({
    required int id,
    String? title,
    String? content,
    String? category,
    String? aiSummary,
    String? aiTags,
    List<String>? attachmentPaths,
    int? totalAttachmentBytes,
    bool resetClassification = true,
  }) async {
    await (_db.update(_db.notes)..where((tbl) => tbl.id.equals(id))).write(
      NotesCompanion(
        title: title != null ? Value(title) : const Value.absent(),
        content: content != null ? Value(content) : const Value.absent(),
        category: category != null ? Value(category) : const Value.absent(),
        aiSummary: Value(aiSummary),
        aiTags: Value(aiTags),
        attachmentPaths: Value(
          attachmentPaths != null ? jsonEncode(attachmentPaths) : null,
        ),
        totalAttachmentBytes: totalAttachmentBytes != null
            ? Value(totalAttachmentBytes)
            : const Value.absent(),
        classificationStatus: resetClassification
            ? const Value('pending')
            : const Value.absent(),
        classificationError: resetClassification
            ? const Value(null)
            : const Value.absent(),
        syncStatus: resetClassification
            ? const Value('pending')
            : const Value.absent(),
        syncedAt: resetClassification
            ? const Value(null)
            : const Value.absent(),
        updatedAt: Value(DateTime.now()),
      ),
    );
  }

  Future<void> delete(int id) async {
    final note = await (_db.select(
      _db.notes,
    )..where((tbl) => tbl.id.equals(id))).getSingleOrNull();
    if (note?.attachmentPaths != null) {
      final paths = List<String>.from(jsonDecode(note!.attachmentPaths!));
      for (final path in paths) {
        try {
          final file = File(path);
          if (await file.exists()) await file.delete();
        } catch (_) {}
      }
    }
    await (_db.delete(_db.notes)..where((tbl) => tbl.id.equals(id))).go();
  }

  Future<void> deleteByUuid(String uuid) async {
    final note = await (_db.select(
      _db.notes,
    )..where((tbl) => tbl.uuid.equals(uuid))).getSingleOrNull();
    if (note?.attachmentPaths != null) {
      final paths = List<String>.from(jsonDecode(note!.attachmentPaths!));
      for (final path in paths) {
        try {
          final file = File(path);
          if (await file.exists()) await file.delete();
        } catch (_) {}
      }
    }
    await (_db.delete(_db.notes)..where((tbl) => tbl.uuid.equals(uuid))).go();
  }

  Future<List<Note>> getAll() async {
    return await (_db.select(_db.notes)
          ..orderBy([(t) => OrderingTerm.desc(t.createdAt)])
          ..limit(200))
        .get();
  }

  Future<List<Note>> getPending() async {
    return await (_db.select(_db.notes)
          ..where((tbl) => tbl.syncStatus.equals('pending'))
          ..orderBy([(t) => OrderingTerm.asc(t.createdAt)]))
        .get();
  }

  Future<Note?> getByUuid(String uuid) async {
    return await (_db.select(
      _db.notes,
    )..where((tbl) => tbl.uuid.equals(uuid))).getSingleOrNull();
  }

  Future<Note?> getById(int id) async {
    return (_db.select(
      _db.notes,
    )..where((tbl) => tbl.id.equals(id))).getSingleOrNull();
  }

  Future<void> updateClassification({
    required int id,
    required String status,
    String? summary,
    String? tags,
    String? error,
  }) async {
    await (_db.update(_db.notes)..where((tbl) => tbl.id.equals(id))).write(
      NotesCompanion(
        classificationStatus: Value(status),
        aiSummary: summary != null ? Value(summary) : const Value.absent(),
        aiTags: tags != null ? Value(tags) : const Value.absent(),
        classificationError: Value(error),
        updatedAt: Value(DateTime.now()),
      ),
    );
  }

  Future<void> markSynced(String uuid) async {
    await (_db.update(_db.notes)..where((tbl) => tbl.uuid.equals(uuid))).write(
      NotesCompanion(
        syncStatus: const Value('synced'),
        syncedAt: Value(DateTime.now()),
      ),
    );
  }

  Future<void> markSyncError(String uuid, String error) async {
    await (_db.update(_db.notes)..where((tbl) => tbl.uuid.equals(uuid))).write(
      NotesCompanion(
        syncStatus: const Value('error'),
        updatedAt: Value(DateTime.now()),
      ),
    );
  }

  Future<void> setSyncStatus(String uuid, String status) async {
    await (_db.update(_db.notes)..where((tbl) => tbl.uuid.equals(uuid))).write(
      NotesCompanion(
        syncStatus: Value(status),
        updatedAt: Value(DateTime.now()),
      ),
    );
  }

  Future<int> deleteSyncedOlderThan(Duration age) async {
    final cutoff = DateTime.now().subtract(age);
    final old =
        await (_db.select(_db.notes)..where(
              (tbl) =>
                  tbl.syncStatus.equals('synced') &
                  tbl.syncedAt.isSmallerThanValue(cutoff),
            ))
            .get();
    for (final note in old) {
      await delete(note.id);
    }
    return old.length;
  }

  Future<int> getPendingCount() async {
    final query = _db.select(_db.notes)
      ..where((tbl) => tbl.syncStatus.equals('pending'));
    final count = await query.get();
    return count.length;
  }

  Stream<List<Note>> watchAll() {
    return (_db.select(
      _db.notes,
    )..orderBy([(t) => OrderingTerm.desc(t.createdAt)])).watch();
  }
}
