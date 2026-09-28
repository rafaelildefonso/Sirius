import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/network/tcp_transfer_client.dart';
import '../../../core/storage/database/database.dart';
import '../../../core/storage/repositories/note_repository.dart';
import '../../../core/device_identity.dart';
import 'note_classifier.dart';

enum NoteSyncState { idle, connecting, syncing, completed, error }

class NoteSyncProgress {
  final NoteSyncState state;
  final int currentItem;
  final int totalItems;
  final int bytesSent;
  final int totalBytes;
  final double speedBps;
  final String? error;

  NoteSyncProgress({
    required this.state,
    this.currentItem = 0,
    this.totalItems = 0,
    this.bytesSent = 0,
    this.totalBytes = 0,
    this.speedBps = 0,
    this.error,
  });
}

class NoteSyncService extends StateNotifier<NoteSyncProgress> {
  final NoteRepository _noteRepo;
  final TcpTransferClient _tcpClient;

  NoteSyncService(this._noteRepo)
    : _tcpClient = TcpTransferClient(),
      super(NoteSyncProgress(state: NoteSyncState.idle));

  /// Sync all pending notes (including binary image attachments) to the PC.
  Future<int> syncPendingNotes({String? host, int port = 8001}) async {
    if (state.state == NoteSyncState.syncing ||
        state.state == NoteSyncState.connecting)
      return 0;

    final pendingNotes = await _noteRepo.getPending();
    if (pendingNotes.isEmpty) return 0;

    state = NoteSyncProgress(
      state: NoteSyncState.connecting,
      totalItems: pendingNotes.length,
    );

    try {
      final deviceId = await DeviceIdentity.getOrCreateId();
      final sessionKey = await DeviceIdentity.getSessionKey() ?? '';
      final serverUrl = await DeviceIdentity.getServerUrl();
      final resolvedHost = host ?? Uri.tryParse(serverUrl ?? '')?.host;
      if (resolvedHost == null || resolvedHost.isEmpty || sessionKey.isEmpty) {
        throw StateError(
          'PC não pareado para sincronização segura de anotações',
        );
      }

      // Calculate total bytes.
      int totalBytes = 0;
      final items = <TcpTransferItem>[];
      for (final note in pendingNotes) {
        final attachments = await _collectAttachments(note);
        int noteBytes = utf8.encode(note.content).length;
        for (final a in attachments) {
          noteBytes += a.bytes.length;
        }
        totalBytes += noteBytes;
        items.add(
          TcpTransferItem(
            uuid: note.uuid,
            type: 'note',
            category: note.category,
            title: note.title,
            content: note.content,
            aiSummary: note.aiSummary,
            aiTags: note.aiTags != null
                ? List<String>.from(jsonDecode(note.aiTags!))
                : null,
            attachments: attachments,
            contentLength: noteBytes,
          ),
        );
      }

      // Try TCP connection.
      try {
        await _tcpClient.connect(resolvedHost, port);
        await _tcpClient.sendHeader(
          sessionKey: sessionKey,
          deviceId: deviceId,
          totalItems: items.length,
          totalBytes: totalBytes,
        );
      } catch (e) {
        for (final note in pendingNotes) {
          await _noteRepo.markSyncError(
            note.uuid,
            'Conexão de anexos com o PC falhou: $e',
          );
        }
        rethrow;
      }

      // Send items one by one.
      int bytesSent = 0;
      var sent = 0;
      for (int i = 0; i < items.length; i++) {
        final item = items[i];
        await _noteRepo.setSyncStatus(item.uuid, 'syncing');

        state = NoteSyncProgress(
          state: NoteSyncState.syncing,
          currentItem: i + 1,
          totalItems: items.length,
          bytesSent: bytesSent,
          totalBytes: totalBytes,
        );

        final result = await _tcpClient.sendNote(
          item,
          itemIndex: i,
          totalItems: items.length,
          onProgress: (progress) {
            state = NoteSyncProgress(
              state: NoteSyncState.syncing,
              currentItem: i + 1,
              totalItems: items.length,
              bytesSent: bytesSent + progress.bytesSent,
              totalBytes: totalBytes,
              speedBps: progress.speedBps,
            );
          },
        );

        if (result.ok) {
          await _noteRepo.markSynced(item.uuid);
          sent++;
          final summary = result.data['summary'] as String?;
          final tags = result.data['tags'];
          if (summary != null || tags is List) {
            await _noteRepo.updateClassification(
              id: pendingNotes[i].id,
              status: 'completed',
              summary: summary,
              tags: tags is List ? jsonEncode(tags) : null,
            );
          } else if (pendingNotes[i].classificationStatus ==
              'fallback_pending') {
            await _noteRepo.updateClassification(
              id: pendingNotes[i].id,
              status: 'failed',
              error: 'A classificação no PC não retornou resultado.',
            );
          }
        } else {
          await _noteRepo.markSyncError(
            item.uuid,
            result.error ?? 'ACK failed',
          );
        }

        bytesSent += item.contentLength;
      }

      await _tcpClient.disconnect();
      state = NoteSyncProgress(
        state: NoteSyncState.completed,
        totalItems: items.length,
        bytesSent: totalBytes,
        totalBytes: totalBytes,
      );
      return sent;
    } catch (e) {
      print('[NoteSyncService] Sync failed: $e');
      state = NoteSyncProgress(state: NoteSyncState.error, error: e.toString());
      await _tcpClient.disconnect();
      return 0;
    }
  }

  /// Classify a note with Gemma (runs in background after save).
  Future<void> classifyNote(Note note) async {
    await _noteRepo.updateClassification(id: note.id, status: 'classifying');
    try {
      final classification = await NoteClassifier.classify(
        content: note.content,
        category: note.category,
        title: note.title,
      );
      if (classification != null) {
        final noteRepo = NoteRepository(AppDatabase());
        await noteRepo.updateNote(
          id: note.id,
          aiSummary: classification.summary,
          aiTags: jsonEncode(classification.tags),
          resetClassification: false,
        );
        await noteRepo.updateClassification(
          id: note.id,
          status: 'completed',
          summary: classification.summary,
          tags: jsonEncode(classification.tags),
        );
      } else {
        await _noteRepo.updateClassification(
          id: note.id,
          status: 'fallback_pending',
          error: NoteClassifier.lastError,
        );
      }
    } catch (e) {
      print('[NoteSyncService] Classification failed: $e');
      await _noteRepo.updateClassification(
        id: note.id,
        status: 'fallback_pending',
        error: e.toString(),
      );
    }
  }

  Future<List<AttachmentData>> _collectAttachments(Note note) async {
    final attachments = <AttachmentData>[];
    if (note.attachmentPaths == null) return attachments;

    final paths = List<String>.from(jsonDecode(note.attachmentPaths!));
    for (final path in paths) {
      try {
        final file = File(path);
        if (await file.exists()) {
          final bytes = await file.readAsBytes();
          attachments.add(
            AttachmentData(
              name: path.split(Platform.pathSeparator).last,
              bytes: bytes,
            ),
          );
        }
      } catch (_) {}
    }
    return attachments;
  }

  @override
  void dispose() {
    _tcpClient.disconnect();
    super.dispose();
  }
}

final noteSyncServiceProvider =
    StateNotifierProvider<NoteSyncService, NoteSyncProgress>((ref) {
      return NoteSyncService(NoteRepository(AppDatabase()));
    });

/// Runs independently of an editor route, so saving a note never has to wait
/// for local inference and closing the screen cannot cancel classification.
Future<void> classifyNoteInBackground(int noteId) async {
  final repository = NoteRepository(AppDatabase());
  final note = await repository.getById(noteId);
  if (note == null) return;
  final service = NoteSyncService(repository);
  try {
    await service.classifyNote(note);
  } finally {
    service.dispose();
  }
}
