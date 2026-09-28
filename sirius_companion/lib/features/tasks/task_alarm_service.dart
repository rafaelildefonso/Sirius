import 'dart:async';
import 'dart:convert';

import 'package:alarm/alarm.dart';
import 'package:drift/drift.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;
import 'package:uuid/uuid.dart';
import 'package:vibration/vibration.dart';

import '../../core/config/constants.dart';
import '../../core/storage/database/database.dart';
import '../../core/storage/repositories/sync_repository.dart';
import '../../core/sync/sync_worker.dart';

/// Central service for scheduled tasks:
/// - quick-add from the phone (offline-first, synced to the PC)
/// - silent native exact alarms (no sound, screen lights up over the
///   lockscreen via full-screen intent, powered by the `alarm` plugin) that
///   fire even when the app process is dead
/// - convergence with the PC via the sync pull (tasks created on PC/voice)
class TaskAlarmService {
  TaskAlarmService._();

  static FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();
  static bool _tzReady = false;
  static bool _initialized = false;
  static bool _bgInitialized = false;

  /// Attention pattern when a task alarm fires: 3 short vibrations.
  static const List<int> _vibrationPattern = [
    0, 400, 600, // buzz
    600, 400, // pause, buzz
    600, 400, // pause, buzz
  ];

  /// Fires the finite attention vibration (3 short bursts). Safe to call on
  /// platforms/devices without a vibrator.
  static Future<void> fireAttentionPattern() async {
    try {
      if (await Vibration.hasVibrator() != true) return;
      await Vibration.vibrate(pattern: _vibrationPattern);
    } catch (e) {
      print('[TaskAlarm] Vibration failed: $e');
    }
  }

  static const String _payloadPrefix = 'task|';

  /// A task found overdue by up to this much still fires when the pull brings
  /// it in late (WorkManager runs at most every ~15 min). Beyond that the
  /// task is closed out instead of ringing hours later.
  static const Duration _overdueFireWindow = Duration(hours: 2);

  /// Stable native-alarm id for a task. The plugin forbids ids 0 and -1.
  static int alarmId(String remoteId) {
    final h = remoteId.hashCode;
    return (h == 0 || h == -1) ? 0x7E57 : h;
  }

  /// Background isolates (WorkManager) never run main(), so both the
  /// notification plugin and the native alarm engine must be initialized
  /// there too before scheduling works.
  static Future<void> _ensureBackgroundReady() async {
    if (_initialized || _bgInitialized) return;
    const settings = InitializationSettings(
      android: AndroidInitializationSettings('@drawable/ic_stat_face'),
    );
    await _plugin.initialize(settings: settings);
    try {
      // Idempotent (single-flight internally); also re-arms stored alarms.
      await Alarm.init();
    } catch (e) {
      print('[TaskAlarm] Alarm engine init failed in background isolate: $e');
    }
    _bgInitialized = true;
  }

  // ── Initialization ────────────────────────────────────────────────────────

  static Future<void> initialize(
    FlutterLocalNotificationsPlugin plugin,
  ) async {
    if (_initialized) return;
    _plugin = plugin;

    await _ensureTimezone();
    await _createChannel();
    await ensurePermissions();

    try {
      await Alarm.init();
      final scheduled = await Alarm.getAlarms();
      print('[TaskAlarm] Native alarm engine ready '
          '(${scheduled.length} alarm(s) armed)');
    } catch (e) {
      print('[TaskAlarm] Native alarm engine init failed: $e');
    }

    // Schedule the daily 00:00 alarm for date-range notifications.
    await _scheduleDailyDateRangeAlarm();

    _initialized = true;
  }

  /// Schedules a daily alarm at 00:00 to fire date-range task notifications.
  static Future<void> _scheduleDailyDateRangeAlarm() async {
    await _ensureTimezone();
    
    const dailyAlarmId = 0xCAFE; // Fixed ID for the daily 00:00 alarm
    
    try {
      // Cancel any existing daily alarm
      await Alarm.stop(dailyAlarmId);
      
      // Calculate next 00:00
      final now = DateTime.now();
      var nextMidnight = DateTime(now.year, now.month, now.day + 1, 0, 0, 0);
      
      // If it's already past 00:00 today, schedule for tomorrow
      if (now.isAfter(nextMidnight)) {
        nextMidnight = nextMidnight.add(const Duration(days: 1));
      }
      
      final ok = await Alarm.set(
        alarmSettings: AlarmSettings(
          id: dailyAlarmId,
          dateTime: nextMidnight,
          assetAudioPath: 'assets/audio/silent.wav',
          loopAudio: false,
          vibrate: false,
          warningNotificationOnKill: false,
          androidFullScreenIntent: true,
          payload: '$_payloadPrefix$dailyAlarmId|DATE_RANGE_DAILY',
          volumeSettings: const VolumeSettings.fixed(
            volume: 0,
            showSystemUI: false,
          ),
          notificationSettings: NotificationSettings(
            title: 'SIRIUS — Verificação diária',
            body: 'Verificando tarefas do dia...',
            stopButton: 'OK',
            androidStopAlarmOnDismiss: true,
          ),
        ),
      );
      
      if (ok) {
        print('[TaskAlarm] Daily 00:00 date-range alarm scheduled for $nextMidnight');
      }
    } catch (e, stack) {
      print('[TaskAlarm] Failed to schedule daily 00:00 alarm: $e');
      print(stack);
    }
  }

  /// Called when the daily 00:00 alarm fires - shows notifications for active date-range tasks.
  static Future<void> onDailyDateRangeAlarm() async {
    await _ensureBackgroundReady();
    await _ensureTimezone();
    
    print('[TaskAlarm] Daily 00:00 alarm fired - showing date-range notifications');
    await fireDateRangeNotificationsForToday();
    
    // Reschedule for next day
    await _scheduleDailyDateRangeAlarm();
  }

  /// Creates the notification channel. Uses a dedicated id (v2) because
  /// Android freezes channel settings after first creation — the old channel
  /// played alarm sounds and could not be silenced in place.
  static Future<void> _createChannel() async {
    const channel = AndroidNotificationChannel(
      AppConstants.taskAlarmChannelId,
      AppConstants.taskAlarmChannelName,
      description: 'Lembretes em tela cheia (silencioso, com vibração)',
      importance: Importance.max,
      playSound: false,
      enableVibration: true,
    );
    await _plugin
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(channel);
  }

  /// (Re-)checks every permission needed for alarms to actually fire.
  /// Called on init AND before each scheduling — Android 13/14 can leave
  /// notifications or exact alarms ungranted after the very first prompt,
  /// which made zonedSchedule throw and the alarm silently never exist.
  static Future<void> ensurePermissions() async {
    try {
      if (!await Permission.notification.isGranted) {
        await Permission.notification.request();
      }
    } catch (_) {}

    try {
      final exact = await Permission.scheduleExactAlarm.status;
      if (!exact.isGranted) {
        await Permission.scheduleExactAlarm.request();
      }
    } catch (_) {
      // scheduleExactAlarm unsupported below API 31 — fine.
    }

    try {
      await _plugin
          .resolvePlatformSpecificImplementation<
              AndroidFlutterLocalNotificationsPlugin>()
          ?.requestFullScreenIntentPermission();
    } catch (_) {}
  }

  static Future<void> _ensureTimezone() async {
    if (_tzReady) return;
    tzdata.initializeTimeZones();
    try {
      final name = await FlutterTimezone.getLocalTimezone();
      tz.setLocalLocation(tz.getLocation(name));
      print('[TaskAlarm] Timezone: $name');
    } catch (e) {
      // Keep going with a fixed-offset zone derived from the device clock
      // instead of silently falling back to UTC. Alarm instants are computed
      // from epoch millis so timing stays exact either way — this mainly
      // fixes display/routing. Note: Etc/GMT names use POSIX (inverted) sign,
      // e.g. Brazil (UTC-3) is 'Etc/GMT+3'.
      final now = DateTime.now();
      final off = now.timeZoneOffset;
      final posixSign = off.isNegative ? '+' : '-';
      final hh = off.inHours.abs().toString().padLeft(2, '0');
      final mm = (off.inMinutes.abs() % 60).toString().padLeft(2, '0');
      final suffix = mm == '00' ? '' : ':$mm';
      final fallbackName = 'Etc/GMT$posixSign$hh$suffix';
      try {
        tz.setLocalLocation(tz.getLocation(fallbackName));
        print('[TaskAlarm] Timezone detection failed ($e) — using $fallbackName');
      } catch (_) {
        print('[TaskAlarm] Timezone detection failed ($e) — using UTC');
      }
    }
    _tzReady = true;
  }

  // ── Quick add (phone) ─────────────────────────────────────────────────────

  /// Creates a task locally, schedules the alarm and queues it for the PC.
  /// Returns the remote id (used as server primary key for dedupe).
  ///
  /// If [isDateRange] is true, creates a date-range task with [startDate] and [endDate].
  /// [dueAt] is optional for date-range tasks (will be null).
  /// If [isDateRange] is false, [dueAt] is required (time-specific task).
  static Future<String> createQuickTask(
    String title, {
    required DateTime? dueAt,
    DateTime? startDate,
    DateTime? endDate,
    bool isDateRange = false,
  }) async {
    final remoteId = const Uuid().v4();
    final now = DateTime.now();
    final cleanTitle = title.trim();

    // Re-check notification/exact-alarm permissions right before scheduling:
    // if they were denied after the first prompt, zonedSchedule would throw
    // and the alarm would silently never fire.
    await ensurePermissions();

    final db = AppDatabase();
    await db.into(db.scheduledTasks).insert(ScheduledTasksCompanion.insert(
          remoteId: remoteId,
          title: cleanTitle,
          dueAt: dueAt == null ? const Value.absent() : Value(dueAt),
          startDate: startDate == null ? const Value.absent() : Value(startDate),
          endDate: endDate == null ? const Value.absent() : Value(endDate),
          isDateRange: Value(isDateRange),
          source: const Value('phone'),
          createdAt: now,
          updatedAt: now,
        ));

    final payload = {
      'id': remoteId,
      'title': cleanTitle,
      'source': 'phone',
      'timestamp': now.toIso8601String(),
      'is_date_range': isDateRange,
    };
    if (dueAt != null) {
      payload['due_at'] = dueAt.toIso8601String();
    }
    if (startDate != null) {
      payload['start_date'] = startDate.toIso8601String();
    }
    if (endDate != null) {
      payload['end_date'] = endDate.toIso8601String();
    }

    await SyncRepository(db).enqueue(
      type: SyncItemType.quickTask.value,
      payloadJson: jsonEncode(payload),
      clientId: const Uuid().v4(),
    );

    if (!isDateRange && dueAt != null) {
      final now = DateTime.now();
      final scheduled = await _scheduleAlarm(
        remoteId: remoteId,
        title: cleanTitle,
        dueAt: dueAt,
      );
      if (!scheduled && dueAt.isAfter(now)) {
        // Due time is in the future today but alarm wasn't scheduled (e.g., engine busy)
        // Show immediate overdue-style notification so user sees it
        await _showOverdueNotification(remoteId, cleanTitle, dueAt);
        await markNotifiedLocally(remoteId);
      } else if (!scheduled) {
        print('[TaskAlarm] WARNING: alarm for "$cleanTitle" was NOT scheduled');
      }
    } else if (isDateRange) {
      // Ensure the daily 00:00 alarm is scheduled for date-range tasks
      await _scheduleDailyDateRangeAlarm();
      
      // If task range includes today, fire 00:00-style notification immediately
      final today = DateTime.now();
      final todayStart = DateTime(today.year, today.month, today.day);
      final todayEnd = todayStart.add(const Duration(days: 1)).subtract(const Duration(milliseconds: 1));
      
      if (startDate != null && endDate != null &&
          !startDate.isAfter(todayEnd) && !endDate.isBefore(todayStart)) {
        await _showDateRangeNotification(remoteId, cleanTitle, startDate!, endDate!);
        await markNotifiedLocally(remoteId);
      }
    }

    // Push to the PC right away so the toast/PC side knows about it.
    await SyncWorker.triggerSync();
    return remoteId;
  }

  // ── User actions ──────────────────────────────────────────────────────────

  static Future<void> markDone(String remoteId, {bool sync = true}) async {
    // Persist the local completion and its outbox item in the same SQLite
    // transaction. This is important for notification actions: the phone may
    // be offline, and Android may stop the background isolate immediately
    // after the action callback returns.
    final db = AppDatabase();
    final now = DateTime.now();
    await db.transaction(() async {
      await (db.update(db.scheduledTasks)
            ..where((tbl) => tbl.remoteId.equals(remoteId)))
          .write(ScheduledTasksCompanion(
            status: const Value('done'),
            alarmScheduled: const Value(false),
            updatedAt: Value(now),
          ));

      if (sync) {
        await db.into(db.syncItems).insert(
          SyncItemsCompanion.insert(
            type: SyncItemType.taskDone.value,
            payloadJson: jsonEncode({
              'task_id': remoteId,
              'timestamp': now.toIso8601String(),
            }),
            clientId: const Uuid().v4(),
            createdAt: now,
          ),
        );
      }
    });

    await _cancelAlarmsFor(remoteId);
    if (sync) {
      try {
        await SyncWorker.triggerSync();
      } catch (e) {
        // Best-effort nudge (WorkManager channel may be unavailable in this
        // isolate); the queued action is pushed by the periodic sync anyway.
        print('[TaskAlarm] Immediate sync trigger failed: $e');
      }
    }
  }

  static Future<void> snooze(String remoteId, {int minutes = 5}) async {
    final db = AppDatabase();
    final task = await (db.select(db.scheduledTasks)
          ..where((tbl) => tbl.remoteId.equals(remoteId)))
        .getSingleOrNull();
    if (task == null) return;

    final base =
        (task.dueAt?.isAfter(DateTime.now()) ?? false) ? (task.dueAt ?? DateTime.now()) : DateTime.now();
    final newDue = base.add(Duration(minutes: minutes));
    await (db.update(db.scheduledTasks)
          ..where((tbl) => tbl.remoteId.equals(remoteId)))
        .write(ScheduledTasksCompanion(
          dueAt: Value(newDue),
          status: const Value('pending'),
          updatedAt: Value(DateTime.now()),
        ));

    // Stop whatever is ringing/scheduled and re-arm at the new time.
    await _cancelAlarmsFor(remoteId);
    await _scheduleAlarm(
      remoteId: remoteId,
      title: task.title,
      dueAt: newDue,
    );

    await _enqueueAction(SyncItemType.taskSnooze, remoteId, minutes: minutes);
    await SyncWorker.triggerSync();
  }

  // ── Queries for UI ────────────────────────────────────────────────────────

  static Future<List<ScheduledTask>> getPendingTasks({int limit = 20}) async {
    final db = AppDatabase();
    return await (db.select(db.scheduledTasks)
          ..where((tbl) =>
              tbl.status.equals('pending') | tbl.status.equals('notified'))
          ..orderBy([
            (u) => OrderingTerm.asc(u.isDateRange), // Date-range tasks first
            (u) => OrderingTerm.asc(u.startDate),   // Then by start date
            (u) => OrderingTerm.asc(u.dueAt),       // Then by due time
          ])
          ..limit(limit))
        .get();
  }

  /// Live local view used by the home screen. It updates immediately when a
  /// background sync inserts or updates tasks in SQLite.
  static Stream<List<ScheduledTask>> watchPendingTasks({int limit = 20}) {
    final db = AppDatabase();
    return (db.select(db.scheduledTasks)
          ..where((tbl) =>
              tbl.status.equals('pending') | tbl.status.equals('notified'))
          ..orderBy([
            (u) => OrderingTerm.asc(u.isDateRange),
            (u) => OrderingTerm.asc(u.startDate),
            (u) => OrderingTerm.asc(u.dueAt),
          ])
          ..limit(limit))
        .watch();
  }

  /// Recovery pass at app start: re-arms EVERY pending task's alarm with the
  /// current settings (also migrates alarms armed by older app versions to
  /// the silent configuration), and closes out stale overdue ones so they
  /// don't sit in the list forever.
  static Future<void> rescheduleMissingAlarms() async {
    await _ensureBackgroundReady();
    await _ensureTimezone();

    final db = AppDatabase();
    try {
      final rows = await (db.select(db.scheduledTasks)
            ..where((tbl) =>
                tbl.status.equals('pending') |
                tbl.status.equals('notified')))
          .get();
      if (rows.isEmpty) return;

      print('[TaskAlarm] Re-arming ${rows.length} task alarm(s)');
      final now = DateTime.now();
      for (final t in rows) {
        // Skip date-range tasks here - they're handled by catchUpMissedDateRangeNotifications
        if (t.isDateRange) continue;
        
        final dueAt = t.dueAt;
        if (dueAt != null && dueAt.isAfter(now)) {
          await _scheduleAlarm(
            remoteId: t.remoteId,
            title: t.title,
            dueAt: dueAt,
          );
        } else if (!t.alarmScheduled &&
            dueAt != null &&
            now.difference(dueAt) <= _overdueFireWindow &&
            t.status == 'pending') {
          // Recently missed — surface it instead of silently skipping.
          await _showOverdueNotification(t.remoteId, t.title, dueAt);
          await markNotifiedLocally(t.remoteId);
        } else if (!t.alarmScheduled) {
          // Long overdue and never fired: close it locally. Server sync
          // trusts the local status, so it won't resurrect on the next pull.
          await _updateStatus(t.remoteId, 'dismissed');
        }
        // else: past-due but an alarm is armed — leave the native engine
        // handle/stop it on its own reconciliation.
      }
    } catch (e) {
      print('[TaskAlarm] Reschedule pass failed: $e');
    }

    // Also catch up on missed date-range notifications
    await catchUpMissedDateRangeNotifications();

    // Ensure the daily 00:00 alarm is scheduled
    await _scheduleDailyDateRangeAlarm();
  }

  /// Fires 00:00 notifications for all active date-range tasks today.
  /// Called by the background worker at midnight.
  static Future<void> fireDateRangeNotificationsForToday() async {
    await _ensureBackgroundReady();
    await _ensureTimezone();

    final db = AppDatabase();
    final today = DateTime.now();
    final todayStart = DateTime(today.year, today.month, today.day);
    final todayEnd = todayStart.add(const Duration(days: 1)).subtract(const Duration(milliseconds: 1));

    try {
      final rows = await (db.select(db.scheduledTasks)
            ..where((tbl) =>
                tbl.isDateRange.equals(true) &
                tbl.status.isIn(['pending', 'notified']) &
                (tbl.startDate.isSmallerOrEqual(Variable(todayEnd))) &
                (tbl.endDate.isBiggerOrEqual(Variable(todayStart)))))
          .get();
      if (rows.isEmpty) return;

      print('[TaskAlarm] Firing ${rows.length} date-range task notification(s) for today');
      for (final t in rows) {
        await _showDateRangeNotification(t.remoteId, t.title, t.startDate!, t.endDate!);
      }
    } catch (e) {
      print('[TaskAlarm] fireDateRangeNotificationsForToday failed: $e');
    }
  }

  /// Checks for missed date-range notifications (e.g., app was off at 00:00).
  /// Call this at app startup to catch up.
  static Future<void> catchUpMissedDateRangeNotifications() async {
    await _ensureBackgroundReady();
    await _ensureTimezone();

    final db = AppDatabase();
    final today = DateTime.now();
    final todayStart = DateTime(today.year, today.month, today.day);
    final todayEnd = todayStart.add(const Duration(days: 1)).subtract(const Duration(milliseconds: 1));

    try {
      final rows = await (db.select(db.scheduledTasks)
            ..where((tbl) =>
                tbl.isDateRange.equals(true) &
                tbl.status.equals('pending') &
                (tbl.startDate.isSmallerOrEqual(Variable(todayEnd))) &
                (tbl.endDate.isBiggerOrEqual(Variable(todayStart)))))
          .get();
      if (rows.isEmpty) return;

      print('[TaskAlarm] Catching up ${rows.length} missed date-range notification(s)');
      for (final t in rows) {
        await _showDateRangeNotification(t.remoteId, t.title, t.startDate!, t.endDate!);
        await markNotifiedLocally(t.remoteId);
      }
    } catch (e) {
      print('[TaskAlarm] catchUpMissedDateRangeNotifications failed: $e');
    }
  }

  /// Notification details for date-range tasks: non-dismissible, only "Concluir" action.
  static AndroidNotificationDetails _dateRangeDetails() {
    return const AndroidNotificationDetails(
      AppConstants.taskAlarmChannelId,
      AppConstants.taskAlarmChannelName,
      channelDescription: 'Lembretes em tela cheia (silencioso, com vibração)',
      icon: 'ic_stat_face',
      importance: Importance.max,
      priority: Priority.max,
      category: AndroidNotificationCategory.alarm,
      playSound: false,
      enableVibration: true,
      visibility: NotificationVisibility.public,
      autoCancel: false, // Non-dismissible
      ongoing: true,     // Stays in notification shade
      actions: [
        // Keep this action in the background. The local completion and outbox
        // write happen before the optional alarm cleanup in markDone.
        AndroidNotificationAction(
          'task_complete_date_range',
          'Concluir',
          cancelNotification: true,
          showsUserInterface: false,
        ),
      ],
    );
  }

  static Future<void> _showDateRangeNotification(
    String remoteId,
    String title,
    DateTime startDate,
    DateTime endDate,
  ) async {
    final startStr = '${startDate.day.toString().padLeft(2, '0')}/${startDate.month.toString().padLeft(2, '0')}';
    final endStr = '${endDate.day.toString().padLeft(2, '0')}/${endDate.month.toString().padLeft(2, '0')}';
    await _plugin.show(
      id: remoteId.hashCode,
      title: '⏰ Tarefa do dia',
      body: '$title ($startStr a $endStr)',
      notificationDetails: NotificationDetails(android: _dateRangeDetails()),
      payload: '$_payloadPrefix$remoteId|$title',
    );
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
      final rawDateRange = map['is_date_range'];
      final isDateRange = rawDateRange == true ||
          rawDateRange == 1 ||
          rawDateRange == '1' ||
          rawDateRange == 'true';
      final startRaw = map['start_date'] as String?;
      final endRaw = map['end_date'] as String?;
      if (remoteId == null || title == null || title.isEmpty) continue;

      DateTime? dueAt;
      DateTime? startDate;
      DateTime? endDate;
      
      if (isDateRange) {
        // Date-range task: parse start_date and end_date
        if (startRaw != null) {
          try {
            startDate = DateTime.parse(startRaw).toLocal();
          } on FormatException {}
        }
        if (endRaw != null) {
          try {
            endDate = DateTime.parse(endRaw).toLocal();
          } on FormatException {}
        }
        if (startDate == null || endDate == null) continue;
      } else {
        // Time-specific task: require due_at
        try {
          dueAt = dueRaw == null ? null : DateTime.parse(dueRaw).toLocal();
        } on FormatException {
          continue;
        }
        if (dueAt == null) continue;
      }

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
        await _cancelAlarmsFor(remoteId);
        continue;
      }

      if (existing != null &&
          existing.status != 'pending' &&
          existing.status != 'notified') {
        // Locally closed already; server says active — trust local.
        continue;
      }

      // Keep the local 'notified' marker (alarm already fired here) so the
      // upsert below doesn't reset it to pending and re-fire on every pull.
      final nextStatus = existing?.status == 'notified' ? 'notified' : 'pending';

      if (existing == null) {
        await db.into(db.scheduledTasks).insert(
              ScheduledTasksCompanion.insert(
                remoteId: remoteId,
                title: title,
                dueAt: dueAt == null ? const Value.absent() : Value(dueAt!),
                startDate: startDate == null ? const Value.absent() : Value(startDate!),
                endDate: endDate == null ? const Value.absent() : Value(endDate!),
                isDateRange: Value(isDateRange),
                notes: Value(map['notes'] as String?),
                status: Value(nextStatus),
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
              dueAt: dueAt == null ? const Value.absent() : Value(dueAt!),
              startDate: startDate == null ? const Value.absent() : Value(startDate!),
              endDate: endDate == null ? const Value.absent() : Value(endDate!),
              isDateRange: Value(isDateRange),
              status: Value(nextStatus),
              updatedAt: Value(now),
            ));
      }

      if (isDateRange) {
        // For date-range tasks, the daily alarm handles subsequent days. On
        // the first pull, however, this task may have been created before the
        // app was installed (or while it was closed), so show today's
        // notification immediately instead of waiting for tomorrow's alarm.
        final rangeStart = startDate;
        final rangeEnd = endDate;
        final today = DateTime.now();
        final todayStart = DateTime(today.year, today.month, today.day);
        final todayEnd = todayStart
            .add(const Duration(days: 1))
            .subtract(const Duration(milliseconds: 1));
        if (nextStatus == 'pending' &&
            rangeStart != null &&
            rangeEnd != null &&
            !rangeStart.isAfter(todayEnd) &&
            !rangeEnd.isBefore(todayStart)) {
          await _showDateRangeNotification(
            remoteId,
            title,
            rangeStart,
            rangeEnd,
          );
          await markNotifiedLocally(remoteId);
        }
      } else if (dueAt != null && dueAt.isAfter(now)) {
        await _scheduleAlarm(
          remoteId: remoteId,
          title: title,
          dueAt: dueAt,
        );
      } else if (dueAt != null && now.difference(dueAt) <= _overdueFireWindow &&
          nextStatus == 'pending') {
        // Recently missed while offline / pulled in late — fire now instead
        // of silently skipping. markNotifiedLocally prevents repeats.
        await _showOverdueNotification(remoteId, title, dueAt!);
        await markNotifiedLocally(remoteId);
      }
    }
  }

  // ── Notification handling ─────────────────────────────────────────────────

  /// Silent heads-up details used for "atrasada" notices (the real ring is
  /// handled natively by the alarm engine, not by a notification).
  static AndroidNotificationDetails _overdueDetails() {
    return const AndroidNotificationDetails(
      AppConstants.taskAlarmChannelId,
      AppConstants.taskAlarmChannelName,
      channelDescription: 'Lembretes em tela cheia (silencioso, com vibração)',
      icon: 'ic_stat_face',
      importance: Importance.max,
      priority: Priority.max,
      category: AndroidNotificationCategory.alarm,
      playSound: false,
      enableVibration: true,
      visibility: NotificationVisibility.public,
      autoCancel: true,
      actions: [
        // Run the action in the background while the phone is unlocked.
        AndroidNotificationAction(
          'task_dismiss',
          'Dispensar',
          cancelNotification: false,
          showsUserInterface: false,
        ),
      ],
    );
  }

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
  ///
  /// Note: action buttons with `showsUserInterface: false` are delivered to
  /// the background callback ([onNotificationBackgroundResponse] in main.dart),
  /// not to the foreground handler — both paths land here.
  static Future<List<String>?> handleNotificationResponse(
    NotificationResponse response,
  ) async {
    final payload = response.payload ?? '';
    if (!payload.startsWith(_payloadPrefix)) return null;
    final parts = handleNotificationRoute(payload);
    if (parts == null) return null;
    final taskId = parts[0];

    switch (response.actionId) {
      case 'task_dismiss':
      case 'task_done': // legacy button from previous app versions
        // Complete the SQLite transaction before initializing optional
        // notification/alarm platform services. This keeps the action
        // durable even when the PC is unreachable or Android ends the
        // background isolate quickly.
        await markDone(taskId);
        return null;
      case 'task_snooze': // legacy button from previous app versions
        await _ensureBackgroundReady();
        await snooze(taskId);
        return null;
      case 'task_complete_date_range': // date-range task completion
        await markDone(taskId);
        return null;
      default:
        await _ensureBackgroundReady();
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

  /// Schedules the native exact alarm: silent (volume 0), screen lights up
  /// over the lockscreen via full-screen intent — survives process death and
  /// reboots. The attention vibration is fired from Dart when it rings.
  /// Never throws — returns whether it worked so callers can log/warn.
  static Future<bool> _scheduleAlarm({
    required String remoteId,
    required String title,
    required DateTime dueAt,
  }) async {
    await _ensureTimezone();
    await _ensureBackgroundReady();

    final db = AppDatabase();
    final id = alarmId(remoteId);
    try {
      final now = DateTime.now();
      if (!dueAt.isAfter(now)) {
        print('[TaskAlarm] Skip: due time already past.');
        await (db.update(db.scheduledTasks)
              ..where((tbl) => tbl.remoteId.equals(remoteId)))
            .write(ScheduledTasksCompanion(alarmScheduled: const Value(false)));
        return false;
      }
      print('[TaskAlarm] Scheduling "$title" for ${dueAt.toIso8601String()} '
          '(in ${dueAt.difference(now).inMinutes} min)');

      final ok = await Alarm.set(
        alarmSettings: AlarmSettings(
          id: id,
          dateTime: dueAt,
          // Bundled silent audio: the engine always plays something through
          // MediaPlayer, and setting the system ALARM volume to 0 can be
          // clamped/rejected (DND, OEMs) — which let the device alarm sound
          // leak through at low volume. Feeding it actual silence removes
          // any audible output regardless of volume handling.
          assetAudioPath: 'assets/audio/silent.wav',
          loopAudio: false,
          // No sound, no native vibration loop: silent playback + the finite
          // Dart-side pattern ([fireAttentionPattern]) when it rings.
          vibrate: false,
          // Off: its "alarm may not ring" warning notification plays the
          // device's default alert sound when posted (the plugin channel has
          // no explicit null sound), which breaks the fully-silent design.
          warningNotificationOnKill: false,
          androidFullScreenIntent: true,
          payload: '$_payloadPrefix$remoteId|$title',
          volumeSettings: const VolumeSettings.fixed(
            volume: 0,
            showSystemUI: false,
          ),
          notificationSettings: NotificationSettings(
            title: '⏰ Hora da tarefa!',
            body: title,
            stopButton: 'Dispensar',
            androidStopAlarmOnDismiss: true,
          ),
        ),
      );

      await (db.update(db.scheduledTasks)
            ..where((tbl) => tbl.remoteId.equals(remoteId)))
          .write(ScheduledTasksCompanion(alarmScheduled: Value(ok)));

      // Schedule a backup notification via flutter_local_notifications.
      // If the native alarm engine fails (process death), the scheduled
      // notification still fires as a heads-up alert.
      if (ok) {
        await _scheduleBackupNotification(
          remoteId: remoteId,
          title: title,
          dueAt: dueAt,
        );
      }

      print('[TaskAlarm] Scheduled ${ok ? 'OK' : 'FAILED'}');
      return ok;
    } catch (e, stack) {
      print('[TaskAlarm] FAILED to schedule "$title": $e');
      print(stack);
      await (db.update(db.scheduledTasks)
            ..where((tbl) => tbl.remoteId.equals(remoteId)))
          .write(ScheduledTasksCompanion(alarmScheduled: const Value(false)));
      return false;
    }
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
      notificationDetails: NotificationDetails(android: _overdueDetails()),
      payload: '$_payloadPrefix$remoteId|$title',
    );
  }

  /// Cancels both engines for a task: the legacy FLN scheduled notification
  /// (old app versions), the native alarm, and the backup scheduled notification.
  static Future<void> _cancelAlarmsFor(String remoteId) async {
    try {
      await _plugin.cancel(id: remoteId.hashCode);
    } catch (_) {}
    try {
      await Alarm.stop(alarmId(remoteId));
    } catch (_) {}
    // Also cancel the backup zonedSchedule notification.
    try {
      await _plugin.cancel(id: remoteId.hashCode + 100000);
    } catch (_) {}
  }

  /// Schedules a backup heads-up notification via flutter_local_notifications
  /// using zonedSchedule. This is a safety net: if the native alarm engine
  /// fails (process death, OEM restrictions), this notification still appears.
  static Future<void> _scheduleBackupNotification({
    required String remoteId,
    required String title,
    required DateTime dueAt,
  }) async {
    try {
      await _ensureTimezone();
      final tzDate = tz.TZDateTime.from(dueAt, tz.local);
      final now = tz.TZDateTime.now(tz.local);
      if (!tzDate.isAfter(now)) return;

      await _plugin.zonedSchedule(
        id: remoteId.hashCode + 100000,
        title: 'Hora da tarefa!',
        body: title,
        scheduledDate: tzDate,
        notificationDetails: const NotificationDetails(
          android: AndroidNotificationDetails(
            AppConstants.taskAlarmChannelId,
            AppConstants.taskAlarmChannelName,
            channelDescription: 'Lembretes em tela cheia (silencioso, com vibração)',
            icon: 'ic_stat_face',
            importance: Importance.max,
            priority: Priority.max,
            category: AndroidNotificationCategory.alarm,
            playSound: false,
            enableVibration: true,
            visibility: NotificationVisibility.public,
          ),
        ),
        androidScheduleMode: AndroidScheduleMode.exactAllowWhileIdle,
        payload: '$_payloadPrefix$remoteId|$title',
      );
    } catch (e) {
      print('[TaskAlarm] Backup notification schedule failed: $e');
    }
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
