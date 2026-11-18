import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/widgets.dart';

import 'sync_worker.dart';

/// Keeps data fresh while resumed, with a two-minute baseline and increasing
/// delays when the PC is unavailable. Reconnect and resume trigger catch-up.
///
/// Background sync is handled separately by the foreground service in
/// [GeofenceManager] — that isolate survives app backgrounding.
class ForegroundSyncService with WidgetsBindingObserver {
  ForegroundSyncService._();

  static final ForegroundSyncService instance = ForegroundSyncService._();

  static const Duration _foregroundInterval = Duration(minutes: 2);

  Timer? _timer;
  StreamSubscription<List<ConnectivityResult>>? _connectivitySub;
  bool _started = false;
  bool _resumed = true;
  DateTime _nextAttempt = DateTime(1970);
  int _failures = 0;

  Future<void> _sync({bool immediate = false}) async {
    if (!immediate && DateTime.now().isBefore(_nextAttempt)) return;
    final result = await SyncWorker.performSync();
    if (result.success) {
      _failures = 0;
      _nextAttempt = DateTime.now().add(_foregroundInterval);
    } else if (result.error != 'Sincronização já em andamento') {
      _failures = (_failures + 1).clamp(1, 5);
      _nextAttempt = DateTime.now().add(Duration(minutes: 1 << _failures));
    }
  }

  void start() {
    if (_started) return;
    _started = true;
    WidgetsBinding.instance.addObserver(this);
    _connectivitySub = Connectivity().onConnectivityChanged.listen((results) {
      // Only sync when Wi-Fi/Ethernet comes back — the PC is a LAN host and
      // is unreachable over cellular, so syncing there would just time out.
      final onLocalNetwork = results.any(
        (r) => r == ConnectivityResult.wifi || r == ConnectivityResult.ethernet,
      );
      if (onLocalNetwork && _resumed) _sync(immediate: true);
    });
    // Catch-up for anything that arrived while the app was closed.
    _sync(immediate: true);
    _startTimer();
  }

  void _startTimer() {
    if (_timer != null) return;
    _timer = Timer.periodic(_foregroundInterval, (_) async {
      // Same gate as the background service: skip the cycle entirely when
      // on cellular (the PC can't be reached, so the request would only
      // burn battery on a doomed reachability check).
      try {
        final results = await Connectivity().checkConnectivity();
        final onLocalNetwork = results.any(
          (r) =>
              r == ConnectivityResult.wifi || r == ConnectivityResult.ethernet,
        );
        if (!onLocalNetwork) return;
      } catch (_) {
        return;
      }
      _sync();
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _resumed = state == AppLifecycleState.resumed;
    if (state == AppLifecycleState.resumed) {
      _sync(immediate: true);
      _startTimer();
    } else {
      _timer?.cancel();
      _timer = null;
    }
  }

  void dispose() {
    _timer?.cancel();
    _timer = null;
    _connectivitySub?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    _started = false;
  }
}
