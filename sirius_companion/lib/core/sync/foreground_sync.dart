import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/widgets.dart';

import 'sync_worker.dart';

/// Keeps data fresh while the app is open: an inline sync every 45 s while
/// resumed, plus a catch-up whenever connectivity returns. This shrinks the
/// PC→phone latency for newly created tasks from up to ~15 min (WorkManager
/// minimum period) to seconds while the user has the app in the foreground.
///
/// Background sync is handled separately by the foreground service in
/// [GeofenceManager] — that isolate survives app backgrounding.
class ForegroundSyncService with WidgetsBindingObserver {
  ForegroundSyncService._();

  static final ForegroundSyncService instance = ForegroundSyncService._();

  static const Duration _foregroundInterval = Duration(seconds: 45);

  Timer? _timer;
  StreamSubscription<List<ConnectivityResult>>? _connectivitySub;
  bool _started = false;

  void start() {
    if (_started) return;
    _started = true;
    WidgetsBinding.instance.addObserver(this);
    _connectivitySub =
        Connectivity().onConnectivityChanged.listen((results) {
      final online = results.any((r) => r != ConnectivityResult.none);
      if (online) SyncWorker.performSync();
    });
    // Catch-up for anything that arrived while the app was closed.
    SyncWorker.performSync();
    // Start the periodic timer immediately.  When the app is backgrounded the
    // main isolate is frozen by the OS so the timer naturally stops firing;
    // background sync is handled by the foreground service.
    _timer = Timer.periodic(
      _foregroundInterval,
      (_) => SyncWorker.performSync(),
    );
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // No-op: the timer is always running in the main isolate.  When the app is
    // backgrounded the OS freezes the isolate so the timer naturally pauses.
    // Background sync is handled by the foreground service.
  }

  void dispose() {
    _timer?.cancel();
    _connectivitySub?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    _started = false;
  }
}
