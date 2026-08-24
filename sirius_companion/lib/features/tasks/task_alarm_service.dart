import 'dart:convert';

import 'package:drift/drift.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;
import 'package:uuid/uuid.dart';

import '../../core/config/constants.dart';
import '../../core/storage/database/database.dart';
import '../../core/storage/repositories/sync_repository.dart';
import '../../core/sync/sync_worker.dart';

/// Central service for scheduled tasks:
/// - quick-add from the phone (offline-first, synced to the PC)
/// - local exact alarms that fire full-screen even when the device is locked
/// - convergence with the PC via the sync pull (tasks created on PC/voice)
class TaskAlarmService {
  TaskAlarmService._();

  static FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();
  static bool _tzReady = false;
  static bool _initialized = false;
  static bool _bgInitialized = false;

  static const String _payloadPrefix = 'task|';
  static const Duration _overdueFireWindow = Duration(minutes: 15);

  /// Background isolates (WorkManager) never run main(), so the plugin must
  /// be initialized there too before zonedSchedule works.
  static Future<void> _ensureBackgroundReady() async {
    if (_initialized || _bgInitialized) return;
    const settings = InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
    );
    await _plugin.initialize(settings: settings);
    _bgInitialized = true;
  }

  // ── Initialization ────────────────────────────────────────────────────────

  static Future<void> initialize(
    FlutterLocalNotificationsPlugin plugin,
  ) async {
    if (_initialized) return;
    _plugin = plugin;

    await _ensureTimezone();

    // Notification permission (Android 13+)
    await Permission.notification.request();

    // Exact alarms (Android 12+ — required for reliable locked-screen firing)
    try {
      final exact = await Permission.scheduleExactAlarm.status;
      if (!exact.isGranted) {
        await Permission.scheduleExactAlarm.request();
      }
    } catch (_) {
      // scheduleExactAlarm unsupported below API 31 — fine.
    }

    // Full-screen intent permission (Android 14+ requires explicit opt-in)
    try {
      await _plugin
          .resolvePlatformSpecificImplementation<
              AndroidFlutterLocalNotificationsPlugin>()
          ?.requestFullScreenIntentPermission();
    } catch (_) {}

    const channel = AndroidNotificationChannel(
      AppConstants.taskAlarmChannelId,
      AppConstants.taskAlarmChannelName,
      description: 'Alarmes em tela cheia para tarefas agendadas',
      importance: Importance.max,
      playSound: true,
      enableVibration: true,
      audioAttributesUsage: AudioAttributesUsage.alarm,
    );
    await _plugin
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(channel);

    _initialized = true;
  }

  static Future<void> _ensureTimezone() async {
    if (_tzReady) return;
    tzdata.initializeTimeZones();
    try {
      final name = await FlutterTimezone.getLocalTimezone();
      tz.setLocalLocation(tz.getLocation(name));
    } catch (_) {
      // Fall back to UTC offsets via TZDateTime.from below.
    }
    _tzReady = true;
  }

  // ── Quick add (phone) ─────────────────────────────────────────────────────

  /// Creates a task locally, schedules the alarm and queues it for the PC.
  /// Returns the remote id (used as server primary key for dedupe).
  static Future<String> createQuickTask(String title, DateTime dueAt) async {
    final remoteId = const Uuid().v4();
    final now = DateTime.now();
    final cleanTitle = title.trim();

    final db = AppDatabase();
    await db.into(db.scheduledTasks).insert(ScheduledTasksCompanion.insert(
          remoteId: remoteId,
          title: cleanTitle,
          dueAt: dueAt,
          source: const Value('phone'),
          createdAt: now,
          updatedAt: now,
        ));

    await SyncRepository(db).enqueue(
      type: SyncItemType.quickTask.value,
      payloadJson: jsonEncode({
        'id': remoteId,
        'title': cleanTitle,
        'due_at': dueAt.toIso8601String(),
        'source': 'phone',
        'timestamp': now.toIso8601String(),
      }),
      clientId: const Uuid().v4(),
    );

    await _scheduleAlarm(remoteId: remoteId, title: cleanTitle, dueAt: dueAt);

    // Push to the PC right away so the toast/PC side knows about it.
    await SyncWorker.triggerSync();
    return remoteId;
  }

  // ── User actions ──────────────────────────────────────────────────────────

  static Future<void> markDone(String remoteId, {bool sync = true}) async {
    await _updateStatus(remoteId, 'done');
    await _cancelAlarm(remoteId.hashCode);
    if (sync) {
      await _enqueueAction(SyncItemType.taskDone, remoteId);
      await SyncWorker.triggerSync();
    }
  }

  static Future<void> snooze(String remoteId, {int minutes = 5}) async {
    final db = AppDatabase();
    final task = await (db.select(db.scheduledTasks)
          ..where((tbl) => tbl.remoteId.equals(remoteId)))
        .getSingleOrNull();
    if (task == null) return;

    final base =
        task.dueAt.isAfter(DateTime.now()) ? task.dueAt : DateTime.now();
    final newDue = base.add(Duration(minutes: minutes));
    await (db.update(db.scheduledTasks)
          ..where((tbl) => tbl.remoteId.equals(remoteId)))
        .write(ScheduledTasksCompanion(
          dueAt: Value(newDue),
          status: const Value('pending'),
          updatedAt: Value(DateTime.now()),
        ));
    await _enqueueAction(SyncItemType.taskSnooze, remoteId, minutes: minutes);
    await SyncWorker.triggerSync();
  }

  // ── Queries for UI ────────────────────────────────────────────────────────

  static Future<List<ScheduledTask>> getPendingTasks({int limit = 20}) async {
    final db = AppDatabase();
    return await (db.select(db.scheduledTasks)
          ..where((tbl) =>
              tbl.status.equals('pending') | tbl.status.equals('notified'))
          ..orderBy([(u) => OrderingTerm.asc(u.dueAt)])
          ..limit(limit))
        .get();
  }

  // ── Server convergence ────────────────────────────────────────────────────

  /// Upserts tasks pulled from the PC: schedules/cancels local alarms and
  /// mirrors status changes (e.g. completed on PC before firing).
  static Future<void> syncFromServer(List<dynamic> tasks) async {
    if (tasks.isEmpty) return;
    await _ensureTimezone();
    await _ensureBackgroundReady();

    final db = AppDatabase();
    for (final raw in tasks) {
      if (raw is! Map) continue;
      final map = Map<String, dynamic>.from(raw);
      final remoteId = map['id'] as String?;
      final title = (map['title'] as String?)?.trim();
      final dueRaw = map['due_at'] as String?;
      final status = (map['status'] as String?) ?? 'pending';
      if (remoteId == null || title == null || title.isEmpty) continue;

      DateTime? dueAt;
      try {
        dueAt = dueRaw == null ? null : DateTime.parse(dueRaw).toLocal();
      } on FormatException {
        continue;
      }
      if (dueAt == null) continue;

      final existing = await (db.select(db.scheduledTasks)
            ..where((tbl) => tbl.remoteId.equals(remoteId)))
          .getSingleOrNull();
      final now = DateTime.now();

      if (status == 'done' || status == 'dismissed') {
        if (existing != null) {
          await (db.update(db.scheduledTasks)
                ..where((tbl) => tbl.remoteId.equals(remoteId)))
              .write(ScheduledTasksCompanion(
                status: Value(status),
                updatedAt: Value(now),
                alarmScheduled: const Value(false),
              ));
        }
        await _cancelAlarm(remoteId.hashCode);
        continue;
      }

      if (existing != null &&
          existing.status != 'pending' &&
          existing.status != 'notified') {
        // Locally closed already; server says active — trust local.
        continue;
      }

      if (existing == null) {
        await db.into(db.scheduledTasks).insert(
              ScheduledTasksCompanion.insert(
                remoteId: remoteId,
                title: title,
                dueAt: dueAt,
                notes: Value(map['notes'] as String?),
                status: const Value('pending'),
                source: Value((map['source'] as String?) ?? 'pc'),
                createdAt: now,
                updatedAt: now,
              ),
            );
      } else {
        await (db.update(db.scheduledTasks)
              ..where((tbl) => tbl.remoteId.equals(remoteId)))
            .write(ScheduledTasksCompanion(
              title: Value(title),
              notes: Value(map['notes'] as String?),
              dueAt: Value(dueAt),
              status: const Value('pending'),
              updatedAt: Value(now),
            ));
      }

      if (dueAt.isAfter(now)) {
        await _scheduleAlarm(
          remoteId: remoteId,
          title: title,
          dueAt: dueAt,
        );
      } else if (now.difference(dueAt) <= _overdueFireWindow &&
          existing == null) {
        // Recently missed while offline — fire now instead of silently skipping.
        await _showOverdueNotification(remoteId, title, dueAt);
      }
    }
  }

  // ── Notification handling ─────────────────────────────────────────────────

  /// Parses a 'task|$id|$title' payload into [taskId, title] for routing,
  /// or null if the payload is not a task alarm.
  static List<String>? handleNotificationRoute(String payload) {
    if (!payload.startsWith(_payloadPrefix)) return null;
    final parts = payload.split('|');
    if (parts.length < 3) return null;
    return [parts[1], parts.sublist(2).join('|')];
  }

  /// Handles a notification tap or action button. Returns the payload parts
  /// ('task|$id|$title') so the app can open the alarm screen on plain taps.
  static Future<List<String>?> handleNotificationResponse(
    NotificationResponse response,
  ) async {
    final payload = response.payload ?? '';
    if (!payload.startsWith(_payloadPrefix)) return null;
    final parts = handleNotificationRoute(payload);
    if (parts == null) return null;
    final taskId = parts[0];

    switch (response.actionId) {
      case 'task_done':
        await markDone(taskId);
        return null;
      case 'task_snooze':
        await snooze(taskId);
        return null;
      default:
        return parts;
    }
  }

  static Future<void> markNotifiedLocally(String remoteId) async {
    final db = AppDatabase();
    await (db.update(db.scheduledTasks)
          ..where((tbl) => tbl.remoteId.equals(remoteId)))
        .write(ScheduledTasksCompanion(
          status: const Value('notified'),
          updatedAt: Value(DateTime.now()),
        ));
  }

  // ── Internals ─────────────────────────────────────────────────────────────

  static AndroidNotificationDetails _alarmDetails() {
    return const AndroidNotificationDetails(
      AppConstants.taskAlarmChannelId,
      AppConstants.taskAlarmChannelName,
      channelDescription: 'Alarmes em tela cheia para tarefas agendadas',
      importance: Importance.max,
      priority: Priority.max,
      category: AndroidNotificationCategory.alarm,
      fullScreenIntent: true,
      visibility: NotificationVisibility.public,
      audioAttributesUsage: AudioAttributesUsage.alarm,
      ongoing: true,
      autoCancel: false,
      actions: [
        AndroidNotificationAction('task_done', 'Feito'),
        AndroidNotificationAction('task_snooze', '+5 min'),
      ],
    );
  }

  static Future<void> _scheduleAlarm({
    required String remoteId,
    required String title,
    required DateTime dueAt,
  }) async {
    await _ensureTimezone();
    final scheduledDate = tz.TZDateTime.from(dueAt, tz.local);
    if (!scheduledDate.isAfter(tz.TZDateTime.now(tz.local))) return;

    await _plugin.zonedSchedule(
      id: remoteId.hashCode,
      title: '⏰ Hora da tarefa!',
      body: title,
      scheduledDate: scheduledDate,
      notificationDetails: NotificationDetails(android: _alarmDetails()),
      androidScheduleMode: AndroidScheduleMode.exactAllowWhileIdle,
      payload: '$_payloadPrefix$remoteId|$title',
    );

    final db = AppDatabase();
    await (db.update(db.scheduledTasks)
          ..where((tbl) => tbl.remoteId.equals(remoteId)))
        .write(ScheduledTasksCompanion(alarmScheduled: const Value(true)));
  }

  static Future<void> _showOverdueNotification(
    String remoteId,
    String title,
    DateTime dueAt,
  ) async {
    final hh = dueAt.toLocal();
    await _plugin.show(
      id: remoteId.hashCode,
      title:
          '⏰ Tarefa atrasada (${hh.hour.toString().padLeft(2, '0')}:${hh.minute.toString().padLeft(2, '0')})',
      body: title,
      notificationDetails: NotificationDetails(android: _alarmDetails()),
      payload: '$_payloadPrefix$remoteId|$title',
    );
  }

  static Future<void> _cancelAlarm(int notificationId) async {
    try {
      await _plugin.cancel(id: notificationId);
    } catch (_) {}
  }

  static Future<void> _updateStatus(String remoteId, String status) async {
    final db = AppDatabase();
    await (db.update(db.scheduledTasks)
          ..where((tbl) => tbl.remoteId.equals(remoteId)))
        .write(ScheduledTasksCompanion(
          status: Value(status),
          alarmScheduled: const Value(false),
          updatedAt: Value(DateTime.now()),
        ));
  }

  static Future<void> _enqueueAction(
    SyncItemType type,
    String remoteId, {
    int minutes = 5,
  }) async {
    final db = AppDatabase();
    await SyncRepository(db).enqueue(
      type: type.value,
      payloadJson: jsonEncode({
        'task_id': remoteId,
        if (type == SyncItemType.taskSnooze) 'minutes': minutes,
        'timestamp': DateTime.now().toIso8601String(),
      }),
      clientId: const Uuid().v4(),
    );
  }
}
