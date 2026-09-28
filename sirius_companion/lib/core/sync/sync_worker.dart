import 'dart:async';
import 'package:workmanager/workmanager.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:uuid/uuid.dart';
import '../../core/network/api_client.dart';
import '../../core/config/constants.dart';
import '../../core/storage/repositories/sync_repository.dart';
import '../../core/storage/repositories/place_repository.dart';
import '../../core/storage/repositories/note_repository.dart';
import '../../core/storage/repositories/place_visit_repository.dart';
import '../../core/storage/models/place.dart' as place_model;
import '../../core/device_identity.dart';
import '../../core/storage/database/database.dart';
import '../../features/tasks/task_alarm_service.dart';
import '../../features/notes/application/note_sync_service.dart';
import 'background_health_monitor.dart';

/// Progress callback for sync operations
typedef SyncProgressCallback = void Function(String message, double progress);

/// WorkManager task name
const String syncTaskName = 'sirius_sync_task';
const String healthCheckTaskName = 'sirius_health_check';
const String taskPullTaskName = 'sirius_task_pull';
const String _lastSyncStorageKey = 'sirius_last_sync_at';

/// Initialize WorkManager
Future<void> initWorkManager() async {
  try {
    await Workmanager().initialize(callbackDispatcher, isInDebugMode: false);

    // Register periodic sync task
    await Workmanager().registerPeriodicTask(
      'sirius_periodic_sync',
      syncTaskName,
      frequency: const Duration(minutes: 15),
      constraints: Constraints(
        networkType: NetworkType.connected,
        requiresBatteryNotLow: true,
      ),
      backoffPolicy: BackoffPolicy.exponential,
      initialDelay: const Duration(minutes: 1),
    );

    // Register periodic health check for the foreground service.
    // Runs independently from the sync task — if the foreground service
    // dies, this task restarts it even when the network is unavailable.
    await Workmanager().registerPeriodicTask(
      'sirius_bg_health_check',
      healthCheckTaskName,
      frequency: const Duration(minutes: 15),
      initialDelay: const Duration(minutes: 2),
    );

    // Register one-time immediate sync task
    await Workmanager().registerOneOffTask(
      'sirius_immediate_sync',
      syncTaskName,
      initialDelay: const Duration(seconds: 10),
      constraints: Constraints(networkType: NetworkType.connected),
    );

    // Dedicated task pull — runs independently from the foreground service.
    // This ensures new tasks from the PC are pulled and alarms are scheduled
    // even when the foreground service has died.
    await Workmanager().registerPeriodicTask(
      'sirius_periodic_task_pull',
      taskPullTaskName,
      frequency: const Duration(minutes: 15),
      constraints: Constraints(
        networkType: NetworkType.connected,
        requiresBatteryNotLow: true,
      ),
      initialDelay: const Duration(minutes: 3),
    );
  } catch (e) {
    print('[WorkManager] Init failed: $e');
  }
}

/// WorkManager callback dispatcher (must be top-level or static)
@pragma('vm:entry-point')
void callbackDispatcher() {
  Workmanager().executeTask((taskName, inputData) async {
    if (taskName == syncTaskName) {
      await SyncWorker.performSync();
    } else if (taskName == healthCheckTaskName) {
      await BackgroundHealthMonitor.restartIfDead();
    } else if (taskName == taskPullTaskName) {
      await SyncWorker.pullTasksOnly();
    }
    return Future.value(true);
  });
}

class SyncWorker {
  static final ApiClient _apiClient = ApiClient.instance;

  static bool _isSyncing = false;

  /// Trigger immediate sync (call from UI)
  static Future<void> triggerSync() async {
    if (_isSyncing) return;
    await Workmanager().registerOneOffTask(
      'sirius_manual_sync_${DateTime.now().millisecondsSinceEpoch}',
      syncTaskName,
      initialDelay: const Duration(seconds: 1),
      constraints: Constraints(networkType: NetworkType.connected),
    );
  }

  static const _lastTaskPullKey = 'sirius_last_task_pull';
  static const Duration _minTaskPullInterval = Duration(minutes: 10);

  /// Pull only tasks from the server and schedule alarms.
  /// This is lighter than a full sync and runs independently.
  /// Skips if the last successful pull was less than 10 minutes ago.
  static Future<void> pullTasksOnly() async {
    try {
      // Guard: skip if pulled recently.
      final prefs = await SharedPreferences.getInstance();
      final lastTs = prefs.getInt(_lastTaskPullKey);
      if (lastTs != null) {
        final lastPull = DateTime.fromMillisecondsSinceEpoch(lastTs);
        if (DateTime.now().difference(lastPull) < _minTaskPullInterval) {
          print(
            '[SyncWorker] Task pull skipped — ran ${DateTime.now().difference(lastPull).inMinutes}m ago',
          );
          return;
        }
      }

      await _apiClient.restoreSavedBaseUrl();

      final isPaired = await DeviceIdentity.isPaired();
      if (!isPaired) return;

      final reachable = await _apiClient.checkServerReachable();
      if (!reachable) return;

      final pullResult = await _apiClient.pullUpdates();
      if (!pullResult.success) return;

      if (pullResult.tasks.isNotEmpty) {
        await TaskAlarmService.syncFromServer(pullResult.tasks);
        print(
          '[SyncWorker] Task pull: processed ${pullResult.tasks.length} task(s)',
        );
      }

      // Record successful pull timestamp.
      await prefs.setInt(
        _lastTaskPullKey,
        DateTime.now().millisecondsSinceEpoch,
      );
    } catch (e) {
      print('[SyncWorker] Task pull failed: $e');
    }
  }

  static const _lastSyncStorage = FlutterSecureStorage();

  static Future<void> _saveLastSync() async {
    await _lastSyncStorage.write(
      key: _lastSyncStorageKey,
      value: DateTime.now().toIso8601String(),
    );
  }

  static Future<DateTime?> _loadLastSync() async {
    final value = await _lastSyncStorage.read(key: _lastSyncStorageKey);
    if (value != null) {
      return DateTime.tryParse(value);
    }
    return null;
  }

  /// Main sync logic
  ///
  /// Safe to call from any isolate: the WorkManager dispatcher calls it on
  /// background cycles and [HomeController] calls it inline for manual syncs.
  ///
  /// Returns a [SyncExecutionResult] with detailed counts of what was sent/received.
  static Future<SyncExecutionResult> performSync({
    SyncProgressCallback? onProgress,
  }) async {
    if (_isSyncing)
      return SyncExecutionResult.error('Sincronização já em andamento');
    _isSyncing = true;

    final db = AppDatabase();
    final syncRepo = SyncRepository(db);
    final placeRepo = PlaceRepository(db);
    final noteRepo = NoteRepository(db);
    final placeVisitRepo = PlaceVisitRepository(db);

    try {
      onProgress?.call('Conectando ao PC...', 0.1);
      await _apiClient.restoreSavedBaseUrl();

      final isPaired = await DeviceIdentity.isPaired();
      if (!isPaired) {
        return SyncExecutionResult.error('Dispositivo não pareado');
      }

      final reachable = await _apiClient.checkServerReachable();
      if (!reachable) {
        return SyncExecutionResult.error(
          'Não foi possível conectar ao PC. Verifique se o SIRIUS está aberto na mesma rede.',
        );
      }

      // 1. Push pending items (commands, tasks, etc.)
      onProgress?.call('Enviando comandos e tarefas ao PC...', 0.2);
      int syncItemsSent = await _pushPendingItems(syncRepo);

      // 2. Push pending notes
      onProgress?.call('Enviando anotações ao PC...', 0.4);
      int notesSent = 0;
      if ((await noteRepo.getPending()).isNotEmpty) {
        final noteSync = NoteSyncService(noteRepo);
        notesSent = await noteSync.syncPendingNotes();
        noteSync.dispose();
      }
      await noteRepo.deleteSyncedOlderThan(const Duration(days: 30));

      // 3. Push pending place visits
      onProgress?.call('Enviando visitas a locais ao PC...', 0.6);
      int visitsSent = 0;
      final pendingVisits = await placeVisitRepo.getPendingSync();
      if (pendingVisits.isNotEmpty) {
        final visitItems = pendingVisits
            .map(
              (visit) => SyncBatchItem(
                clientId: const Uuid().v4(),
                type: 'place_visit',
                payload: {
                  'uuid': visit.uuid,
                  'place_id': visit.placeId,
                  'place_name': visit.placeName,
                  'entered_at': visit.enteredAt.toIso8601String(),
                  'exited_at': visit.exitedAt?.toIso8601String(),
                  'duration_seconds': visit.durationSeconds,
                },
              ),
            )
            .toList();

        final visitResults = await _apiClient.syncBatch(visitItems);
        if (visitResults.success) {
          final syncedUuids = <String>[];
          for (final result in visitResults.results) {
            if (result.status == 'processed') {
              final idx = visitResults.results.indexOf(result);
              if (idx < pendingVisits.length) {
                syncedUuids.add(pendingVisits[idx].uuid);
              }
            }
          }
          // TCP/HTTP response confirmed processed on PC: delete from phone
          for (final uuid in syncedUuids) {
            await placeVisitRepo.deleteByUuid(uuid);
          }
          visitsSent = syncedUuids.length;
        }
      }

      // 4. Pull updates from server
      onProgress?.call('Buscando atualizações e novas tarefas do PC...', 0.8);
      final pullResult = await _pullFromServer(syncRepo, placeRepo);
      final int itemsPulled = pullResult;

      // 5. Clean old synced items
      await syncRepo.clearSynced();

      // 6. Persist last sync timestamp
      await _saveLastSync();

      onProgress?.call('Sincronização concluída com sucesso!', 1.0);
      final totalSent = syncItemsSent + notesSent + visitsSent;
      print(
        '[SyncWorker] Sync completed: sent $totalSent (notes=$notesSent, visits=$visitsSent, sync=$syncItemsSent), received $itemsPulled',
      );

      return SyncExecutionResult.success(
        notesSent: notesSent,
        visitsSent: visitsSent,
        syncItemsSent: syncItemsSent,
        itemsPulled: itemsPulled,
      );
    } on Exception catch (e) {
      print('[SyncWorker] Sync failed: $e');
      return SyncExecutionResult.error(e.toString());
    } catch (e, stack) {
      print('[SyncWorker] Sync failed: $e');
      print(stack);
      return SyncExecutionResult.error(e.toString());
    } finally {
      _isSyncing = false;
    }
  }

  static Future<int> _pushPendingItems(SyncRepository syncRepo) async {
    final pendingItems = await syncRepo.getPending(limit: 100);
    if (pendingItems.isEmpty) return 0;

    print('[SyncWorker] Pushing ${pendingItems.length} pending items');

    // Convert to API format
    final apiItems = pendingItems
        .map(
          (item) => SyncBatchItem(
            clientId: item.clientId,
            type: item.type,
            payload: item.payload,
          ),
        )
        .toList();

    final results = await _apiClient.syncBatch(apiItems);

    if (results.success) {
      // Mark successfully synced items
      final syncedClientIds = results.results
          .where((r) => r.status == 'processed')
          .map((r) => r.clientId)
          .toList();

      if (syncedClientIds.isNotEmpty) {
        await syncRepo.markSynced(syncedClientIds);
        print('[SyncWorker] Marked ${syncedClientIds.length} items as synced');
        return syncedClientIds.length;
      }

      // Handle failed items - increment retry count
      for (final result in results.results.where((r) => r.status == 'failed')) {
        await syncRepo.incrementRetry(
          result.clientId,
          result.error ?? 'Unknown error',
        );
      }
      return 0;
    } else {
      // Increment retry for all items
      for (final item in pendingItems) {
        await syncRepo.incrementRetry(
          item.clientId,
          results.error ?? 'Sync failed',
        );
      }
      return 0;
    }
  }

  static Future<int> _pullFromServer(
    SyncRepository syncRepo,
    PlaceRepository placeRepo,
  ) async {
    final pullResult = await _apiClient.pullUpdates();

    if (!pullResult.success) {
      print('[SyncWorker] Pull failed: ${pullResult.error}');
      return 0;
    }

    int count = 0;

    // Process new commands from PC
    for (final cmdJson in pullResult.commands) {
      await _processIncomingCommand(cmdJson);
      count++;
    }

    // Process new/updated places
    for (final placeJson in pullResult.places) {
      final place = place_model.Place.fromJson(placeJson);
      await placeRepo.save(place);
      count++;
    }

    // Process scheduled tasks (schedule local alarms / mirror PC changes)
    if (pullResult.tasks.isNotEmpty) {
      try {
        await TaskAlarmService.syncFromServer(pullResult.tasks);
        count += pullResult.tasks.length;
        print(
          '[SyncWorker] Processed ${pullResult.tasks.length} scheduled task(s)',
        );
      } catch (e) {
        print('[SyncWorker] Task sync failed: $e');
      }
    }

    return count;
  }

  static Future<void> _processIncomingCommand(
    Map<String, dynamic> cmdJson,
  ) async {
    // Commands pulled from the PC (e.g. "enviar pro meu celular") are shown
    // as a local notification. They must NOT be re-enqueued into the sync
    // queue — that would push them straight back to the PC next cycle.
    final text = cmdJson['text'] as String?;
    if (text == null || text.isEmpty) return;

    try {
      final notifications = FlutterLocalNotificationsPlugin();
      const androidDetails = AndroidNotificationDetails(
        AppConstants.pcMessageChannelId,
        AppConstants.pcMessageChannelName,
        channelDescription: 'Mensagens enviadas pelo SIRIUS no PC',
        icon: 'ic_stat_face',
        importance: Importance.high,
        priority: Priority.high,
      );
      const details = NotificationDetails(android: androidDetails);
      await notifications.show(
        id: DateTime.now().millisecondsSinceEpoch ~/ 1000 % 2147483647,
        title: 'SIRIUS',
        body: text,
        notificationDetails: details,
      );
    } catch (e) {
      print('[SyncWorker] Failed to show PC command notification: $e');
    }
  }
}

/// Sync status for UI
class SyncStatus {
  final bool isSyncing;
  final int pendingCount;
  final int failedCount;
  final int pendingNotesCount;
  final int pendingVisitsCount;
  final int totalPendingCount;
  final DateTime? lastSync;
  final String? lastError;

  SyncStatus({
    required this.isSyncing,
    required this.pendingCount,
    required this.failedCount,
    this.pendingNotesCount = 0,
    this.pendingVisitsCount = 0,
    this.totalPendingCount = 0,
    this.lastSync,
    this.lastError,
  });

  static Future<SyncStatus> current() async {
    final db = AppDatabase();
    final syncRepo = SyncRepository(db);
    final noteRepo = NoteRepository(db);
    final placeVisitRepo = PlaceVisitRepository(db);
    final pending = await syncRepo.getPendingCount();
    final failed = await syncRepo.getFailedCount();
    final pendingNotes = await noteRepo.getPendingCount();
    final pendingVisits = await placeVisitRepo.getPendingSyncCount();
    final totalPending = pending + pendingNotes + pendingVisits;
    final lastSync = await SyncWorker._loadLastSync();
    return SyncStatus(
      isSyncing: SyncWorker._isSyncing,
      pendingCount: pending,
      failedCount: failed,
      pendingNotesCount: pendingNotes,
      pendingVisitsCount: pendingVisits,
      totalPendingCount: totalPending,
      lastSync: lastSync,
    );
  }
}

/// Result of a sync execution with detailed counts
class SyncExecutionResult {
  final bool success;
  final int notesSent;
  final int visitsSent;
  final int syncItemsSent;
  final int itemsPulled;
  final String? error;

  SyncExecutionResult._({
    required this.success,
    this.notesSent = 0,
    this.visitsSent = 0,
    this.syncItemsSent = 0,
    this.itemsPulled = 0,
    this.error,
  });

  factory SyncExecutionResult.success({
    int notesSent = 0,
    int visitsSent = 0,
    int syncItemsSent = 0,
    int itemsPulled = 0,
  }) {
    return SyncExecutionResult._(
      success: true,
      notesSent: notesSent,
      visitsSent: visitsSent,
      syncItemsSent: syncItemsSent,
      itemsPulled: itemsPulled,
    );
  }

  factory SyncExecutionResult.error(String message) {
    return SyncExecutionResult._(success: false, error: message);
  }

  String get summary {
    if (!success) return error ?? 'Falha na sincronização';
    final parts = <String>[];
    if (notesSent > 0)
      parts.add('$notesSent ${notesSent == 1 ? "anotação" : "anotações"}');
    if (visitsSent > 0)
      parts.add('$visitsSent ${visitsSent == 1 ? "visita" : "visitas"}');
    if (syncItemsSent > 0)
      parts.add('$syncItemsSent ${syncItemsSent == 1 ? "item" : "itens"}');
    if (itemsPulled > 0)
      parts.add('$itemsPulled ${itemsPulled == 1 ? "recebido" : "recebidos"}');
    if (parts.isEmpty) return 'Sincronizado (sem pendências)';
    return 'Sync: ${parts.join(", ")}';
  }
}
