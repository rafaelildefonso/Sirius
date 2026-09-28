import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'dart:async';
import '../../../../core/sync/sync_worker.dart';
import '../../../../core/storage/repositories/sync_repository.dart';
import '../../../../core/storage/repositories/note_repository.dart';
import '../../../../core/storage/repositories/place_visit_repository.dart';
import '../../../../core/storage/database/database.dart';
import '../../../../core/device_identity.dart';
import '../../../../core/network/api_client.dart';
import '../../../../core/storage/models/sync_item.dart' as sync_model;

final homeControllerProvider = StateNotifierProvider<HomeController, HomeState>((ref) {
  return HomeController();
});

/// Reactive provider that tracks whether the device is currently paired.
/// Used by the auth gate to navigate to pairing screen on unpair.
final isPairedProvider = StateProvider<bool>((ref) => false);

class HomeState {
  final bool isSyncing;
  final bool isConnected;
  final int pendingCount;
  final int failedCount;
  final int pendingNotesCount;
  final int pendingTasksCount;
  final int pendingVisitsCount;
  final int totalPendingCount;
  final DateTime? lastSync;
  final String? lastError;
  final String? syncProgressMessage;
  final SyncExecutionResult? lastSyncResult;
  final List<sync_model.SyncItem> recentCommands;

  HomeState({
    this.isSyncing = false,
    this.isConnected = false,
    this.pendingCount = 0,
    this.failedCount = 0,
    this.pendingNotesCount = 0,
    this.pendingTasksCount = 0,
    this.pendingVisitsCount = 0,
    this.totalPendingCount = 0,
    this.lastSync,
    this.lastError,
    this.syncProgressMessage,
    this.lastSyncResult,
    this.recentCommands = const [],
  });

  HomeState copyWith({
    bool? isSyncing,
    bool? isConnected,
    int? pendingCount,
    int? failedCount,
    int? pendingNotesCount,
    int? pendingTasksCount,
    int? pendingVisitsCount,
    int? totalPendingCount,
    DateTime? lastSync,
    String? lastError,
    String? syncProgressMessage,
    SyncExecutionResult? lastSyncResult,
    List<sync_model.SyncItem>? recentCommands,
  }) {
    return HomeState(
      isSyncing: isSyncing ?? this.isSyncing,
      isConnected: isConnected ?? this.isConnected,
      pendingCount: pendingCount ?? this.pendingCount,
      failedCount: failedCount ?? this.failedCount,
      pendingNotesCount: pendingNotesCount ?? this.pendingNotesCount,
      pendingTasksCount: pendingTasksCount ?? this.pendingTasksCount,
      pendingVisitsCount: pendingVisitsCount ?? this.pendingVisitsCount,
      totalPendingCount: totalPendingCount ?? this.totalPendingCount,
      lastSync: lastSync ?? this.lastSync,
      lastError: lastError ?? this.lastError,
      syncProgressMessage: syncProgressMessage ?? this.syncProgressMessage,
      lastSyncResult: lastSyncResult ?? this.lastSyncResult,
      recentCommands: recentCommands ?? this.recentCommands,
    );
  }
}

class HomeController extends StateNotifier<HomeState> {
  final SyncRepository _syncRepo;
  Timer? _refreshTimer;
  Timer? _connectivityTimer;
  bool _mounted = true;

  HomeController()
    : _syncRepo = SyncRepository(AppDatabase()),
      super(HomeState()) {
    _init();
  }

  Future<void> _init() async {
    await loadStatus();
    await checkConnectivity();
    _startPeriodicRefresh();
  }

  Future<void> loadStatus() async {
    try {
      final status = await SyncStatus.current();
      final pendingItems = await _syncRepo.getPending(limit: 20);
      final noteRepo = NoteRepository(AppDatabase());
      final placeVisitRepo = PlaceVisitRepository(AppDatabase());
      final pendingNotes = await noteRepo.getPendingCount();
      final pendingVisits = await placeVisitRepo.getPendingSyncCount();
      final totalPending = status.pendingCount + pendingNotes + pendingVisits;
      
      state = state.copyWith(
        pendingCount: status.pendingCount,
        failedCount: status.failedCount,
        pendingNotesCount: pendingNotes,
        pendingTasksCount: 0, // Tasks are handled separately
        pendingVisitsCount: pendingVisits,
        totalPendingCount: totalPending,
        lastSync: status.lastSync,
        recentCommands: pendingItems.cast<sync_model.SyncItem>(),
      );
    } catch (e) {
      state = state.copyWith(lastError: e.toString());
    }
  }

  /// Check server reachability and update [isConnected] state.
  Future<void> checkConnectivity() async {
    try {
      await ApiClient.instance.restoreSavedBaseUrl();
      final isPaired = await DeviceIdentity.isPaired();
      if (!isPaired) {
        state = state.copyWith(isConnected: false);
        return;
      }
      final reachable = await ApiClient.instance.checkServerReachable();
      if (!reachable) {
        // Try LAN discovery
        final discoveredUrl = await ApiClient.instance.discoverServerOnLan();
        if (discoveredUrl != null) {
          state = state.copyWith(isConnected: true);
        } else {
          state = state.copyWith(isConnected: false);
        }
      } else {
        state = state.copyWith(isConnected: true);
      }
    } catch (_) {
      state = state.copyWith(isConnected: false);
    }
  }

  void _startPeriodicRefresh() {
    _refreshTimer?.cancel();
    _refreshTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      loadStatus();
      checkConnectivity();
    });
  }

  /// Runs the sync inline (same isolate as the UI).
  Future<SyncExecutionResult?> triggerManualSync() async {
    if (state.isSyncing) return null;
    state = state.copyWith(
      isSyncing: true,
      lastError: null,
      syncProgressMessage: 'Conectando ao PC...',
    );

    try {
      // Check connectivity first
      await checkConnectivity();
      if (!state.isConnected) {
        state = state.copyWith(syncProgressMessage: 'Procurando PC na rede local...');
        final discoveredUrl = await ApiClient.instance.discoverServerOnLan();
        if (discoveredUrl == null) {
          final result = SyncExecutionResult.error(
            'Não foi possível conectar ao PC. Verifique se o SIRIUS está aberto na mesma rede.',
          );
          state = state.copyWith(
            isSyncing: false,
            lastError: result.error,
            lastSyncResult: result,
            syncProgressMessage: null,
          );
          return result;
        }
        // Re-check connectivity with discovered URL
        await checkConnectivity();
        if (!state.isConnected) {
          final result = SyncExecutionResult.error(
            'Não foi possível conectar ao PC após descoberta na rede.',
          );
          state = state.copyWith(
            isSyncing: false,
            lastError: result.error,
            lastSyncResult: result,
            syncProgressMessage: null,
          );
          return result;
        }
      }

      state = state.copyWith(syncProgressMessage: 'Enviando anotações e tarefas ao PC...');
      final result = await SyncWorker.performSync(
        onProgress: (message, progress) {
          if (_mounted) {
            state = state.copyWith(syncProgressMessage: message);
          }
        },
      );

      if (result.success) {
        state = state.copyWith(
          syncProgressMessage: 'Sincronização concluída com sucesso!',
        );
      } else {
        state = state.copyWith(
          syncProgressMessage: 'Falha na sincronização',
        );
      }

      // Clear progress message after a delay
      Future.delayed(const Duration(seconds: 3), () {
        if (_mounted && state.syncProgressMessage != null && !state.isSyncing) {
          state = state.copyWith(syncProgressMessage: null);
        }
      });

      state = state.copyWith(
        isSyncing: false,
        lastSyncResult: result,
        lastError: result.success ? null : result.error,
      );

      await loadStatus();
      return result;
    } catch (e) {
      final result = SyncExecutionResult.error(e.toString());
      state = state.copyWith(
        isSyncing: false,
        lastError: e.toString(),
        lastSyncResult: result,
        syncProgressMessage: null,
      );
      return result;
    }
  }

  Future<void> unpair() async {
    await DeviceIdentity.clearPairing();
    ApiClient.instance.clearDeviceToken();
  }

  @override
  void dispose() {
    _mounted = false;
    _refreshTimer?.cancel();
    _connectivityTimer?.cancel();
    super.dispose();
  }
}
