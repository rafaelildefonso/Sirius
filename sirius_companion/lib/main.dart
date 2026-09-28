import 'dart:async';

import 'package:alarm/alarm.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'core/storage/database/database.dart';
import 'core/sync/sync_worker.dart';
import 'core/sync/foreground_sync.dart';
import 'core/sync/background_health_monitor.dart';
import 'core/network/api_client.dart';
import 'features/pairing/presentation/pairing_screen.dart';
import 'features/home/presentation/home_screen.dart';
import 'features/home/application/home_controller.dart';
import 'core/device_identity.dart';
import 'features/locations/application/geofence_manager.dart';
import 'features/tasks/task_alarm_service.dart';
import 'features/tasks/presentation/alarm_screen.dart';

final _notificationPlugin = FlutterLocalNotificationsPlugin();
final _navigatorKey = GlobalKey<NavigatorState>();

/// Fixed native-alarm id for the daily 00:00 date-range verification alarm.
const int _dailyDateRangeAlarmId = 0xCAFE;

/// Handles notification actions while the app UI is not shown (background
/// isolate spawned by flutter_local_notifications when the action has
/// `showsUserInterface: false`). Must be top-level with `vm:entry-point` so
/// the plugin can resolve it via `PluginUtilities.getCallbackHandle`.
@pragma('vm:entry-point')
void onNotificationBackgroundResponse(NotificationResponse response) {
  // Background isolates never run main(), so the binding (binary messenger)
  // must be initialized here — otherwise every plugin channel and the local
  // DB (path_provider) throw "binding was accessed before it was initialized"
  // and the action aborts silently.
  WidgetsFlutterBinding.ensureInitialized();
  TaskAlarmService.handleNotificationResponse(response).catchError((e) {
    print('[TaskAlarm] Background notification response failed: $e');
    return null;
  });
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProviderScope(child: SiriusCompanionApp()));
}

class SiriusCompanionApp extends ConsumerStatefulWidget {
  const SiriusCompanionApp({super.key});

  @override
  ConsumerState<SiriusCompanionApp> createState() => _SiriusCompanionAppState();
}

class _SiriusCompanionAppState extends ConsumerState<SiriusCompanionApp> {
  final AppDatabase _db = AppDatabase();
  StreamSubscription? _ringingSub;
  int? _displayedRingId;
  bool _wasRinging = false;

  @override
  void initState() {
    super.initState();
    _initApp();
  }

  Future<void> _initApp() async {
    // 1. Notifications — lightweight, needed before any UI.
    const androidSettings = AndroidInitializationSettings('@drawable/ic_stat_face');
    const initSettings = InitializationSettings(android: androidSettings);
    await _notificationPlugin.initialize(
      settings: initSettings,
      onDidReceiveNotificationResponse: _handleNotificationResponse,
      onDidReceiveBackgroundNotificationResponse: onNotificationBackgroundResponse,
    );

    _listenForRingingAlarms();

    // 2. Check if launched from notification.
    try {
      final launch = await _notificationPlugin.getNotificationAppLaunchDetails();
      if (launch?.didNotificationLaunchApp ?? false) {
        final response = launch?.notificationResponse;
        final payload = response?.payload;
        if (payload != null && payload.startsWith('task|')) {
          if (response?.actionId != null) {
            // Launched by a notification action button (e.g. "Concluir"):
            // run the action instead of opening the ringing screen.
            _handleNotificationResponse(response!);
          } else {
            WidgetsBinding.instance.addPostFrameCallback((_) {
              _openAlarmFromPayload(payload);
            });
          }
        }
      }
    } catch (_) {}

    // 3. DB + pairing (quick, but still yield the frame).
    await _db.customSelect('SELECT 1').get();
    final paired = await DeviceIdentity.isPaired();
    ref.read(isPairedProvider.notifier).state = paired;

    // 4. Heavy / non-essential work — fire and forget, never block UI.
    _initBackground();
  }

  /// Background init that must NOT block the first frame.
  Future<void> _initBackground() async {
    try {
      await ApiClient.instance.restoreSavedBaseUrl();
    } catch (_) {}

    try {
      await initWorkManager();
    } catch (_) {}

    try {
      await TaskAlarmService.initialize(_notificationPlugin);
      await TaskAlarmService.rescheduleMissingAlarms();
    } catch (_) {}

    ForegroundSyncService.instance.start();

    try {
      await ref.read(geofenceManagerProvider).initialize();
    } catch (_) {}

    try {
      await BackgroundHealthMonitor.restartIfDead();
    } catch (_) {}
  }

  void _listenForRingingAlarms() {
    _ringingSub = Alarm.ringing.listen((ringing) {
      final alarms = [...ringing.alarms]
        ..sort((a, b) => a.dateTime.compareTo(b.dateTime));
      // The internal daily 00:00 alarm is a silent verification pass, not a
      // user-facing task ring — no attention vibration for it.
      final taskAlarms =
          alarms.where((a) => a.id != _dailyDateRangeAlarmId).toList();
      final hasRinging = taskAlarms.isNotEmpty;
      if (hasRinging && !_wasRinging) {
        TaskAlarmService.fireAttentionPattern();
      }
      _wasRinging = hasRinging;
      if (alarms.any((a) => a.id == _dailyDateRangeAlarmId)) {
        TaskAlarmService.onDailyDateRangeAlarm();
      }
      for (final alarm in taskAlarms) {
        if (_displayedRingId == alarm.id) continue;
        _openRingScreen(alarm);
        break;
      }
    });
  }

  Future<void> _openRingScreen(AlarmSettings alarm) async {
    _displayedRingId = alarm.id;
    for (var i = 0; i < 60 && _navigatorKey.currentState == null; i++) {
      await WidgetsBinding.instance.endOfFrame;
    }
    final nav = _navigatorKey.currentState;
    if (nav == null) {
      _displayedRingId = null;
      return;
    }
    final parts = TaskAlarmService.handleNotificationRoute(alarm.payload ?? '');
    await nav.push(
      MaterialPageRoute(
        builder: (_) => AlarmScreen(
          alarmId: alarm.id,
          taskId: parts?[0] ?? '',
          title: parts?[1] ?? alarm.notificationSettings.body,
        ),
      ),
    );
    if (_displayedRingId == alarm.id) _displayedRingId = null;
  }

  void _openAlarmFromPayload(String payload) {
    final parts = TaskAlarmService.handleNotificationRoute(payload);
    if (parts == null) return;
    _navigatorKey.currentState?.push(
      MaterialPageRoute(
        builder: (_) => AlarmScreen(
          alarmId: TaskAlarmService.alarmId(parts[0]),
          taskId: parts[0],
          title: parts[1],
        ),
      ),
    );
  }

  void _handleNotificationResponse(NotificationResponse response) {
    if (response.actionId == 'confirm') {
      final payload = response.payload;
      if (payload != null) {
        final parts = payload.split('|');
        if (parts.length == 2) {
          ref.read(geofenceManagerProvider).confirmPlace(parts[0], parts[1]);
        }
      }
      return;
    }

    TaskAlarmService.handleNotificationResponse(response).then((openParts) {
      if (openParts != null) {
        _navigatorKey.currentState?.push(
          MaterialPageRoute(
            builder: (_) => AlarmScreen(
              alarmId: TaskAlarmService.alarmId(openParts[0]),
              taskId: openParts[0],
              title: openParts[1],
            ),
          ),
        );
      }
    });
  }

  @override
  void dispose() {
    _ringingSub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SIRIUS Companion',
      debugShowCheckedModeBanner: false,
      navigatorKey: _navigatorKey,
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF6366F1),
          secondary: Color(0xFF22C55E),
          surface: Color(0xFF0D1117),
          surfaceContainerHighest: Color(0xFF1F2937),
          onSurface: Colors.white,
          error: Color(0xFFEF4444),
        ),
        scaffoldBackgroundColor: const Color(0xFF07090F),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFF07090F),
          elevation: 0,
          iconTheme: IconThemeData(color: Colors.white),
          titleTextStyle: TextStyle(
            color: Colors.white,
            fontSize: 20,
            fontWeight: FontWeight.w600,
          ),
        ),
        cardTheme: CardThemeData(
          color: const Color(0xFFFFFFFF).withOpacity(0.04),
          elevation: 0,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: const Color(0xFFFFFFFF).withOpacity(0.05),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: BorderSide(color: const Color(0xFFFFFFFF).withOpacity(0.1)),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: BorderSide(color: const Color(0xFFFFFFFF).withOpacity(0.1)),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: const BorderSide(color: Color(0xFF6366F1), width: 2),
          ),
        ),
        elevatedButtonTheme: ElevatedButtonThemeData(
          style: ElevatedButton.styleFrom(
            backgroundColor: const Color(0xFF6366F1),
            foregroundColor: Colors.white,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 24),
          ),
        ),
        outlinedButtonTheme: OutlinedButtonThemeData(
          style: OutlinedButton.styleFrom(
            foregroundColor: Colors.white,
            side: BorderSide(color: const Color(0xFFFFFFFF).withOpacity(0.2)),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 24),
          ),
        ),
      ),
      home: const _AuthGate(),
    );
  }
}

/// Reactive auth gate — watches [isPairedProvider] so that unpairing
/// immediately navigates back to the pairing screen.
class _AuthGate extends ConsumerWidget {
  const _AuthGate();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isPaired = ref.watch(isPairedProvider);

    if (isPaired) {
      return const HomeScreen();
    }
    return const PairingScreen();
  }
}