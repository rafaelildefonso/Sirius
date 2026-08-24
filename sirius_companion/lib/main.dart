import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'core/storage/database/database.dart';
import 'core/sync/sync_worker.dart';
import 'core/network/api_client.dart';
import 'features/pairing/presentation/pairing_screen.dart';
import 'features/home/presentation/home_screen.dart';
import 'core/device_identity.dart';
import 'features/locations/application/geofence_manager.dart';
import 'features/tasks/task_alarm_service.dart';
import 'features/tasks/presentation/alarm_screen.dart';

final _notificationPlugin = FlutterLocalNotificationsPlugin();
final _navigatorKey = GlobalKey<NavigatorState>();

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

  @override
  void initState() {
    super.initState();
    _initApp();
  }

  Future<void> _initApp() async {
    await _db.customSelect('SELECT 1').get();
    // Point the API at the PC saved during QR pairing (if any).
    await ApiClient.instance.restoreSavedBaseUrl();
    await initWorkManager();

    const androidSettings = AndroidInitializationSettings('@mipmap/ic_launcher');
    const initSettings = InitializationSettings(android: androidSettings);
    await _notificationPlugin.initialize(
      settings: initSettings,
      onDidReceiveNotificationResponse: _handleNotificationResponse,
    );

    // Task alarms: channels, permissions, exact scheduling.
    await TaskAlarmService.initialize(_notificationPlugin);

    // Launched by a full-screen task alarm (possibly over the lockscreen)?
    try {
      final launch = await _notificationPlugin.getNotificationAppLaunchDetails();
      if (launch?.didNotificationLaunchApp ?? false) {
        final payload = launch?.notificationResponse?.payload;
        if (payload != null && payload.startsWith('task|')) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            _openAlarmFromPayload(payload);
          });
        }
      }
    } catch (_) {}

    await ref.read(geofenceManagerProvider).initialize();
  }

  void _openAlarmFromPayload(String payload) {
    final parts = TaskAlarmService.handleNotificationRoute(payload);
    if (parts == null) return;
    _navigatorKey.currentState?.push(
      MaterialPageRoute(
        builder: (_) => AlarmScreen(taskId: parts[0], title: parts[1]),
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

    // Task alarm actions / tap.
    TaskAlarmService.handleNotificationResponse(response).then((openParts) {
      if (openParts != null) {
        _navigatorKey.currentState?.push(
          MaterialPageRoute(
            builder: (_) =>
                AlarmScreen(taskId: openParts[0], title: openParts[1]),
          ),
        );
      }
    });
  }

  @override
  void dispose() {
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

class _AuthGate extends ConsumerWidget {
  const _AuthGate();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return FutureBuilder<bool>(
      future: DeviceIdentity.isPaired(),
      builder: (context, snapshot) {
        if (!snapshot.hasData) {
          return const Scaffold(
            backgroundColor: Color(0xFF07090F),
            body: Center(
              child: CircularProgressIndicator(color: Color(0xFF6366F1)),
            ),
          );
        }
        if (snapshot.data == true) {
          return const HomeScreen();
        }
        return const PairingScreen();
      },
    );
  }
}