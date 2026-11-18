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
import '../../features/tasks/recurring_task_service.dart';
import '../../features/tasks/routine_service.dart';
import '../../features/notes/application/note_sync_service.dart';
import 'background_health_monitor.dart';

/// Progress callback for sync operations
typedef SyncProgressCallback = void Function(String message, double progress);

/// WorkManager task names
const String syncTaskName = 'sirius_sync_task';
const String maintenanceTaskName = 'sirius_maintenance';
// Legacy periodic task names — still cancelled on init (see initWorkManager)
// and still handled by the dispatcher for any instances already enqueued.
const String healthCheckTaskName = 'sirius_health_check';
const String taskPullTaskName = 'sirius_task_pull';
const String notifReassertTaskName = 'sirius_notif_reassert';
const String recurringTaskGenerationTaskName =
    'sirius_recurring_task_generation';
const String _lastSyncStorageKey = 'sirius_last_sync_at';

/// Initialize WorkManager
Future<void> initWorkManager() async {
  try {
    await Workmanager().initialize(callbackDispatcher, isInDebugMode: false);

    // Cancel the four legacy periodic tasks (pre-consolidation) so devices
    // upgrading from an older build don't keep running them forever.
    final wm = Workmanager();
    for (final legacy in const [
      'sirius_periodic_sync',
      'sirius_bg_health_check',
      'sirius_periodic_task_pull',
      'sirius_notif_reassert',
    ]) {
      try {
        await wm.cancelByUniqueName(legacy);
      } catch (_) {}
    }

    // Single unified periodic maintenance task (replaces the four separate
    // 15-min tasks). One enqueued job instead of four is far friendlier to
    // Doze/battery; each cycle runs the health check, task pull, full sync
    // and notification re-assert in sequence. 60 min is well above the
    // WorkManager 15-min floor. `unmetered` + `batteryNotLow` mean it only
    // runs on Wi-Fi/charging-friendly conditions — which is when the phone
    // can actually reach the PC on the LAN anyway.
    await wm.registerPeriodicTask(
      'sirius_periodic_maintenance',
      maintenanceTaskName,
      frequency: const Duration(minutes: 60),
      constraints: Constraints(
        networkType: NetworkType.unmetered,
        requiresBatteryNotLow: true,
      ),
      backoffPolicy: BackoffPolicy.exponential,
      initialDelay: const Duration(minutes: 1),
    );

    // Recurrence generation is device-local and must continue while the PC is
    // offline. It has no network constraint and only materializes today's
    // occurrence, so it remains lightweight.
    await wm.registerPeriodicTask(
      recurringTaskGenerationTaskName,
      recurringTaskGenerationTaskName,
      frequency: const Duration(minutes: 15),
      initialDelay: const Duration(minutes: 1),
    );
  } catch (e) {
    print('[WorkManager] Init failed: $e');
  }
}

/// WorkManager callback dispatcher (must be top-level or static)
@pragma('vm:entry-point')
void callbackDispatcher() {
  Workmanager().executeTask((taskName, inputData) async {
    if (taskName == maintenanceTaskName) {
      // Unified cycle: health first (cheap), then network-bound work.
      await BackgroundHealthMonitor.restartIfDead();
      await SyncWorker.performSync();
      await TaskAlarmService.ensureTodayNotificationsActive();
    } else if (taskName == recurringTaskGenerationTaskName) {
      await TaskAlarmService.prepareBackground();
      await RecurringTaskService.generateDueOccurrences();
      await RoutineService.generateUpcomingOccurrences();
    } else if (taskName == syncTaskName) {
      await SyncWorker.performSync();
    } else if (taskName == healthCheckTaskName) {
      // Legacy task still enqueued on devices upgrading from older builds.
      await BackgroundHealthMonitor.restartIfDead();
    } else if (taskName == taskPullTaskName) {
      await SyncWorker.pullTasksOnly();
    } else if (taskName == notifReassertTaskName) {
      await TaskAlarmService.ensureTodayNotificationsActive();
    }
    return Future.value(true);
  });
}

class SyncWorker {
  static final ApiClient _apiClient = ApiClient.instance;

  static bool _isSyncing = false;

  // SQLite coordinates independent Flutter isolates, unlike a static boolean.
  // A lease also recovers if Android kills an isolate mid-sync.
  static Future<bool> _acquireSyncLease(AppDatabase db, String owner) async {
    await db.customStatement(
      'CREATE TABLE IF NOT EXISTS sync_lease '
      '(id INTEGER PRIMARY KEY, owner TEXT NOT NULL, expires_at INTEGER NOT NULL)',
    );
    final now = DateTime.now().millisecondsSinceEpoch;
    await db.customStatement(
      'INSERT INTO sync_lease (id, owner, expires_at) VALUES (1, ?, ?) '
      'ON CONFLICT(id) DO UPDATE SET owner = excluded.owner, '
      'expires_at = excluded.expires_at WHERE sync_lease.expires_at < ?',
      [owner, now + const Duration(minutes: 30).inMilliseconds, now],
    );
    final row = await db
        .customSelect('SELECT owner FROM sync_lease WHERE id = 1')
        .getSingle();
    return row.read<String>('owner') == owner;
  }

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

      if (pullResult.recurring.isNotEmpty) {
        await RecurringTaskService.syncFromServer(pullResult.recurring);
      }
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
    bool announceToPc = false,
  }) async {
    if (_isSyncing)
      return SyncExecutionResult.error('Sincronização já em andamento');
    _isSyncing = true;

    final db = AppDatabase();
    final leaseOwner = const Uuid().v4();
    var leaseAcquired = false;
    final syncRepo = SyncRepository(db);
    final placeRepo = PlaceRepository(db);
    final noteRepo = NoteRepository(db);
    final placeVisitRepo = PlaceVisitRepository(db);
    final syncErrors = <String>[];
    var syncItemsSent = 0;
    var notesSent = 0;
    var visitsSent = 0;
    var itemsPulled = 0;

    try {
      leaseAcquired = await _acquireSyncLease(db, leaseOwner);
      if (!leaseAcquired) {
        return SyncExecutionResult.error('Sincronização já em andamento');
      }
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
      try {
        final pushResult = await _pushPendingItems(
          syncRepo,
          announceToPc: announceToPc,
        );
        syncItemsSent = pushResult.sent;
        if (pushResult.error != null) {
          syncErrors.add('Comandos/tarefas: ${pushResult.error}');
        }
      } catch (e) {
        syncErrors.add('Comandos/tarefas: $e');
      }

      // 2. Push pending notes
      onProgress?.call('Enviando anotações ao PC...', 0.4);
      try {
        if ((await noteRepo.getPending()).isNotEmpty) {
          final noteSync = NoteSyncService(noteRepo);
          try {
            notesSent = await noteSync.syncPendingNotes();
            final noteError = noteSync.syncError;
            if (noteError != null) {
              syncErrors.add('Anotações: $noteError');
            }
          } finally {
            noteSync.dispose();
          }
        }
        await noteRepo.deleteSyncedOlderThan(const Duration(days: 30));
      } catch (e) {
        syncErrors.add('Anotações: $e');
      }

      // 3. Push pending place visits
      onProgress?.call('Enviando visitas a locais ao PC...', 0.6);
      try {
        final pendingVisits = await placeVisitRepo.getPendingSync();
        if (pendingVisits.isNotEmpty) {
          final visitItems = pendingVisits.map((visit) {
            return SyncBatchItem(
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
            );
          }).toList();

          final visitResults = await _apiClient.syncBatch(
            visitItems,
            announceToPc: announceToPc,
          );
          if (!visitResults.success) {
            syncErrors.add(
              'Visitas: ${visitResults.error ?? 'Falha ao sincronizar visitas'}',
            );
          } else {
            final visitUuidByClientId = {
              for (var i = 0; i < visitItems.length; i++)
                visitItems[i].clientId: pendingVisits[i].uuid,
            };
            final processedIds = visitResults.results
                .where((result) => result.status == 'processed')
                .map((result) => result.clientId)
                .toSet();
            final syncedUuids = processedIds
                .map((clientId) => visitUuidByClientId[clientId])
                .whereType<String>()
                .toList();
            for (final uuid in syncedUuids) {
              await placeVisitRepo.deleteByUuid(uuid);
            }
            visitsSent = syncedUuids.length;

            if (syncedUuids.length != pendingVisits.length) {
              final failed = visitResults.results
                  .where((result) => result.status != 'processed')
                  .toList();
              syncErrors.add(
                'Visitas: ${failed.isNotEmpty ? failed.first.error ?? 'Nem todas as visitas foram confirmadas pelo PC' : 'Nem todas as visitas foram confirmadas pelo PC'}',
              );
            }
          }
        }
      } catch (e) {
        syncErrors.add('Visitas: $e');
      }

      // 4. Pull updates from server
      onProgress?.call('Buscando atualizações e novas tarefas do PC...', 0.8);
      try {
        itemsPulled = await _pullFromServer(syncRepo, placeRepo);
      } catch (e) {
        syncErrors.add('Atualizações do PC: $e');
      }

      // 5. Clean old synced items
      await syncRepo.clearSynced();

      // 6. Persist last sync timestamp
      if (syncErrors.isEmpty) await _saveLastSync();

      final totalSent = syncItemsSent + notesSent + visitsSent;
      if (syncErrors.isNotEmpty) {
        onProgress?.call('Sincronização concluída com falhas', 1.0);
        return SyncExecutionResult.error(
          '${syncErrors.join('\n')}\nEnviados: $totalSent '
          '(anotações=$notesSent, visitas=$visitsSent, tarefas/comandos=$syncItemsSent); '
          'recebidos: $itemsPulled.',
          notesSent: notesSent,
          visitsSent: visitsSent,
          syncItemsSent: syncItemsSent,
          itemsPulled: itemsPulled,
        );
      }

      onProgress?.call('Sincronização concluída com sucesso!', 1.0);
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
      if (leaseAcquired) {
        try {
          await db.customStatement(
            'DELETE FROM sync_lease WHERE id = 1 AND owner = ?',
            [leaseOwner],
          );
        } catch (_) {}
      }
      _isSyncing = false;
    }
  }

  static Future<_PendingPushResult> _pushPendingItems(
    SyncRepository syncRepo, {
    required bool announceToPc,
  }) async {
    final pendingItems = await syncRepo.getPending(limit: 100);
    if (pendingItems.isEmpty) return const _PendingPushResult(sent: 0);

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

    final results = await _apiClient.syncBatch(
      apiItems,
      announceToPc: announceToPc,
    );

    if (!results.success) {
      // Increment retry for all items
      for (final item in pendingItems) {
        await syncRepo.incrementRetry(
          item.clientId,
          results.error ?? 'Sync failed',
        );
      }
      return _PendingPushResult(
        sent: 0,
        error: results.error ?? 'Falha ao enviar itens ao PC',
      );
    }

    final submittedClientIds = pendingItems
        .map((item) => item.clientId)
        .toList();
    final syncedClientIds = results.confirmedClientIds(submittedClientIds);
    if (syncedClientIds.isNotEmpty) {
      await syncRepo.markSynced(syncedClientIds);
      print('[SyncWorker] Marked ${syncedClientIds.length} items as synced');
    }

    final syncedClientIdSet = syncedClientIds.toSet();
    final resultByClientId = {
      for (final result in results.results) result.clientId: result,
    };
    final failedItems = pendingItems
        .where((item) => !syncedClientIdSet.contains(item.clientId))
        .toList();
    for (final item in failedItems) {
      await syncRepo.incrementRetry(
        item.clientId,
        resultByClientId[item.clientId]?.error ?? 'Item não confirmado pelo PC',
      );
    }
    final firstFailed = failedItems.isEmpty ? null : failedItems.first;
    final firstFailedResult = firstFailed == null
        ? null
        : resultByClientId[firstFailed.clientId];
    final pendingTypeCounts = <String, int>{};
    for (final item in pendingItems) {
      pendingTypeCounts[item.type] = (pendingTypeCounts[item.type] ?? 0) + 1;
    }
    return _PendingPushResult(
      sent: syncedClientIds.length,
      error: firstFailed == null
          ? null
          : firstFailedResult?.error ??
                (firstFailedResult != null
                    ? 'O PC informou falha ao processar "${firstFailed.type}".'
                    : 'PC confirmou ${results.processed} de ${pendingItems.length} '
                          'item(ns), mas não retornou confirmação para todos. '
                          'Confirmações detalhadas: ${results.results.length}. '
                          'Tipos no lote: '
                          '${pendingTypeCounts.entries.map((entry) => '${entry.key}=${entry.value}').join(', ')}.'),
    );
  }

  static Future<int> _pullFromServer(
    SyncRepository syncRepo,
    PlaceRepository placeRepo,
  ) async {
    final pullResult = await _apiClient.pullUpdates();

    if (!pullResult.success) {
      print('[SyncWorker] Pull failed: ${pullResult.error}');
      throw StateError(
        pullResult.error ?? 'Falha ao buscar atualizações do PC',
      );
    }

    int count = 0;
    final errors = <String>[];

    // Process new commands from PC
    for (final cmdJson in pullResult.commands) {
      try {
        await _processIncomingCommand(cmdJson);
        count++;
      } catch (e) {
        errors.add('comando: $e');
      }
    }

    // Process new/updated places
    for (final placeJson in pullResult.places) {
      try {
        final place = place_model.Place.fromJson(placeJson);
        await placeRepo.save(place);
        count++;
      } catch (e) {
        errors.add('local: $e');
      }
    }

    if (pullResult.recurring.isNotEmpty) {
      try {
        await RecurringTaskService.syncFromServer(pullResult.recurring);
        count += pullResult.recurring.length;
      } catch (e) {
        print('[SyncWorker] Recurring task sync failed: $e');
        errors.add('tarefas recorrentes: $e');
      }
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
        errors.add('tarefas: $e');
      }
    }
    if (errors.isNotEmpty) {
      throw StateError(errors.join('; '));
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

class _PendingPushResult {
  final int sent;
  final String? error;

  const _PendingPushResult({required this.sent, this.error});
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

  factory SyncExecutionResult.error(
    String message, {
    int notesSent = 0,
    int visitsSent = 0,
    int syncItemsSent = 0,
    int itemsPulled = 0,
  }) {
    return SyncExecutionResult._(
      success: false,
      notesSent: notesSent,
      visitsSent: visitsSent,
      syncItemsSent: syncItemsSent,
      itemsPulled: itemsPulled,
      error: message,
    );
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
