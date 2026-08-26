import 'dart:async';
import 'package:workmanager/workmanager.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import '../../core/network/api_client.dart';
import '../../core/config/constants.dart';
import '../../core/storage/repositories/sync_repository.dart';
import '../../core/storage/repositories/place_repository.dart';
import '../../core/storage/models/place.dart' as place_model;
import '../../core/device_identity.dart';
import '../../core/storage/database/database.dart';
import '../../features/tasks/task_alarm_service.dart';

/// WorkManager task name
const String syncTaskName = 'sirius_sync_task';
const String _lastSyncStorageKey = 'sirius_last_sync_at';

/// Initialize WorkManager
Future<void> initWorkManager() async {
  await Workmanager().initialize(
    callbackDispatcher,
    isInDebugMode: false,
  );
  
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
  
  // Register one-time immediate sync task
  await Workmanager().registerOneOffTask(
    'sirius_immediate_sync',
    syncTaskName,
    initialDelay: const Duration(seconds: 10),
    constraints: Constraints(networkType: NetworkType.connected),
  );
}

/// WorkManager callback dispatcher (must be top-level or static)
@pragma('vm:entry-point')
void callbackDispatcher() {
  Workmanager().executeTask((taskName, inputData) async {
    if (taskName == syncTaskName) {
      await SyncWorker.performSync();
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
  static Future<void> performSync() async {
    if (_isSyncing) return;
    _isSyncing = true;

    // AppDatabase is a singleton; creating it here never opens a new
    // connection, so this can safely live outside the try/catch below.
    final db = AppDatabase();
    final syncRepo = SyncRepository(db);
    final placeRepo = PlaceRepository(db);

    try {
      // Ensure the persisted PC URL is applied — WorkManager runs this in a
      // fresh isolate where the ApiClient singleton starts from the default.
      await _apiClient.restoreSavedBaseUrl();

      // Check if paired
      final isPaired = await DeviceIdentity.isPaired();
      if (!isPaired) {
        print('[SyncWorker] Not paired, skipping sync');
        return;
      }

      // Check server reachable
      final reachable = await _apiClient.checkServerReachable();
      if (!reachable) {
        print('[SyncWorker] Server not reachable');
        return;
      }

      // 1. Push pending items
      await _pushPendingItems(syncRepo);

      // 2. Pull updates from server
      await _pullFromServer(syncRepo, placeRepo);

      // 3. Clean old synced items
      await syncRepo.clearSynced();

      // 4. Persist last sync timestamp
      await _saveLastSync();

      print('[SyncWorker] Sync completed successfully');
    } catch (e, stack) {
      print('[SyncWorker] Sync failed: $e');
      print(stack);
    } finally {
      _isSyncing = false;
    }
  }
  
  static Future<void> _pushPendingItems(SyncRepository syncRepo) async {
    final pendingItems = await syncRepo.getPending(limit: 100);
    if (pendingItems.isEmpty) return;
    
    print('[SyncWorker] Pushing ${pendingItems.length} pending items');
    
    // Convert to API format
    final apiItems = pendingItems.map((item) => SyncBatchItem(
      clientId: item.clientId,
      type: item.type,
      payload: item.payload,
    )).toList();
    
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
      }
      
      // Handle failed items - increment retry count
      for (final result in results.results.where((r) => r.status == 'failed')) {
        await syncRepo.incrementRetry(result.clientId, result.error ?? 'Unknown error');
      }
    } else {
      // Increment retry for all items
      for (final item in pendingItems) {
        await syncRepo.incrementRetry(item.clientId, results.error ?? 'Sync failed');
      }
    }
  }
  
  static Future<void> _pullFromServer(SyncRepository syncRepo, PlaceRepository placeRepo) async {
    final pullResult = await _apiClient.pullUpdates();
    
    if (!pullResult.success) {
      print('[SyncWorker] Pull failed: ${pullResult.error}');
      return;
    }
    
    // Process new commands from PC
    for (final cmdJson in pullResult.commands) {
      await _processIncomingCommand(cmdJson);
    }
    
    // Process new/updated places
    for (final placeJson in pullResult.places) {
      final place = place_model.Place.fromJson(placeJson);
      await placeRepo.save(place);
    }
    
    // Process scheduled tasks (schedule local alarms / mirror PC changes)
    if (pullResult.tasks.isNotEmpty) {
      try {
        await TaskAlarmService.syncFromServer(pullResult.tasks);
        print('[SyncWorker] Processed ${pullResult.tasks.length} scheduled task(s)');
      } catch (e) {
        print('[SyncWorker] Task sync failed: $e');
      }
    }
    
    // Refresh geofences if places changed
    // if (pullResult.places.isNotEmpty) {
    //   GeofenceManager.refreshGeofences();
    // }
  }
  
  static Future<void> _processIncomingCommand(Map<String, dynamic> cmdJson) async {
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
  final DateTime? lastSync;
  final String? lastError;
  
  SyncStatus({
    required this.isSyncing,
    required this.pendingCount,
    required this.failedCount,
    this.lastSync,
    this.lastError,
  });
  
  static Future<SyncStatus> current() async {
    final db = AppDatabase();
    final syncRepo = SyncRepository(db);
    final pending = await syncRepo.getPendingCount();
    final failed = await syncRepo.getFailedCount();
    final lastSync = await SyncWorker._loadLastSync();
    return SyncStatus(
      isSyncing: SyncWorker._isSyncing,
      pendingCount: pending,
      failedCount: failed,
      lastSync: lastSync,
    );
  }
}