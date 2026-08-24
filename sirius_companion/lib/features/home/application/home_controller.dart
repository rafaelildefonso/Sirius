import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'dart:async';
import '../../../../core/sync/sync_worker.dart';
import '../../../../core/storage/repositories/sync_repository.dart';
import '../../../../core/storage/database/database.dart';
import '../../../../core/device_identity.dart';
import '../../../../core/storage/models/sync_item.dart' as sync_model;

final homeControllerProvider = StateNotifierProvider<HomeController, HomeState>((ref) {
  return HomeController();
});

class HomeState {
  final bool isSyncing;
  final int pendingCount;
  final int failedCount;
  final DateTime? lastSync;
  final String? lastError;
  final List<sync_model.SyncItem> recentCommands;

  HomeState({
    this.isSyncing = false,
    this.pendingCount = 0,
    this.failedCount = 0,
    this.lastSync,
    this.lastError,
    this.recentCommands = const [],
  });

  HomeState copyWith({
    bool? isSyncing,
    int? pendingCount,
    int? failedCount,
    DateTime? lastSync,
    String? lastError,
    List<sync_model.SyncItem>? recentCommands,
  }) {
    return HomeState(
      isSyncing: isSyncing ?? this.isSyncing,
      pendingCount: pendingCount ?? this.pendingCount,
      failedCount: failedCount ?? this.failedCount,
      lastSync: lastSync ?? this.lastSync,
      lastError: lastError ?? this.lastError,
      recentCommands: recentCommands ?? this.recentCommands,
    );
  }
}

class HomeController extends StateNotifier<HomeState> {
  final SyncRepository _syncRepo;
  Timer? _refreshTimer;

  HomeController()
    : _syncRepo = SyncRepository(AppDatabase()),
      super(HomeState()) {
    _init();
  }

  Future<void> _init() async {
    await loadStatus();
    _startPeriodicRefresh();
  }

  /// Refreshes counters/timestamps only. Never touches [HomeState.isSyncing]:
  /// that flag belongs exclusively to [triggerManualSync], since the worker
  /// runs inline in this isolate now.
  Future<void> loadStatus() async {
    try {
      final status = await SyncStatus.current();
      final pendingItems = await _syncRepo.getPending(limit: 20);
      state = state.copyWith(
        pendingCount: status.pendingCount,
        failedCount: status.failedCount,
        lastSync: status.lastSync,
        recentCommands: pendingItems.cast<sync_model.SyncItem>(),
      );
    } catch (e) {
      state = state.copyWith(lastError: e.toString());
    }
  }

  void _startPeriodicRefresh() {
    _refreshTimer?.cancel();
    _refreshTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      loadStatus();
    });
  }

  /// Runs the sync inline (same isolate as the UI) so [HomeState.isSyncing]
  /// reflects the real operation instead of a cross-isolate static that was
  /// always false here. The spinner can never get stuck: [isSyncing] is
  /// guaranteed to be reset in the finally block.
  Future<void> triggerManualSync() async {
    if (state.isSyncing) return;
    state = state.copyWith(isSyncing: true, lastError: null);
    try {
      await SyncWorker.performSync();
    } catch (e) {
      state = state.copyWith(lastError: e.toString());
    } finally {
      await loadStatus();
      state = state.copyWith(isSyncing: false);
    }
  }

  Future<void> unpair() async {
    await DeviceIdentity.clearPairing();
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    super.dispose();
  }
}
