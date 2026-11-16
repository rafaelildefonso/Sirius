import 'dart:async';

import 'package:alarm/alarm.dart';
import 'package:flutter/material.dart';

import '../task_alarm_service.dart';
import '../simulated_call_policy.dart';

const _weekdays = [
  'segunda-feira',
  'terça-feira',
  'quarta-feira',
  'quinta-feira',
  'sexta-feira',
  'sábado',
  'domingo',
];

const _months = [
  'janeiro',
  'fevereiro',
  'março',
  'abril',
  'maio',
  'junho',
  'julho',
  'agosto',
  'setembro',
  'outubro',
  'novembro',
  'dezembro',
];

/// Full-screen ringing screen shown when a task alarm fires: live clock,
/// bell, task name and two actions — Dispensar (done) and Adiar (+5 min).
/// Shown over the lockscreen via the native full-screen intent; auto-closes
/// if the alarm stops ringing from elsewhere.
class AlarmScreen extends StatefulWidget {
  final int alarmId;
  final String taskId;
  final String title;
  final bool simulatedCall;
  final Future<void> Function()? onAcceptCall;
  final Future<void> Function(bool dnd)? onRejectCall;
  final Future<void> Function()? onMissedCall;

  const AlarmScreen({
    super.key,
    required this.alarmId,
    required this.taskId,
    required this.title,
    this.simulatedCall = false,
    this.onAcceptCall,
    this.onRejectCall,
    this.onMissedCall,
  });

  @override
  State<AlarmScreen> createState() => _AlarmScreenState();
}

class _AlarmScreenState extends State<AlarmScreen> {
  Timer? _clockTimer;
  Timer? _callTimeout;
  // Element type (AlarmSet) is intentionally left unannotated — the class
  // isn't exported by the package's public API.
  StreamSubscription? _ringingSub;
  DateTime _now = DateTime.now();
  bool _closing = false;

  @override
  void initState() {
    super.initState();
    _clockTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _now = DateTime.now());
    });
    if (widget.simulatedCall) {
      // Missed calls are closed locally after 30 seconds and never retried.
      _callTimeout = Timer(SimulatedCallPolicy.ringScreenDuration, () async {
        if (_closing) return;
        _closing = true;
        try {
          if (widget.onMissedCall != null) {
            await widget.onMissedCall!();
          } else {
            await TaskAlarmService.markSimulatedCallMissed(widget.taskId);
          }
        } catch (error) {
          debugPrint('[AlarmScreen] Failed to close missed call: $error');
        } finally {
          _popToRoot();
        }
      });
    }
    // The alarm may be stopped outside this screen (notification button,
    // another alarm entry point). Close along with it.
    _ringingSub = Alarm.ringing.listen((ringing) {
      final stillRinging = ringing.alarms.any((a) => a.id == widget.alarmId);
      if (!stillRinging && !_closing && !widget.simulatedCall) {
        if (mounted) setState(() => _closing = true);
        _popToRoot();
      }
    });
  }

  @override
  void dispose() {
    _clockTimer?.cancel();
    _callTimeout?.cancel();
    _ringingSub?.cancel();
    super.dispose();
  }

  void _popToRoot() {
    if (!mounted) return;
    Navigator.of(context).popUntil((route) => route.isFirst);
  }

  Future<void> _dismiss() async {
    if (_closing) return;
    setState(() => _closing = true);
    try {
      // Stop natively first — guaranteed even if the local task row is gone.
      await Alarm.stop(widget.alarmId);
    } catch (_) {}
    await TaskAlarmService.markDone(widget.taskId);
    _popToRoot();
  }

  Future<void> _snooze() async {
    if (_closing) return;
    setState(() => _closing = true);
    try {
      await Alarm.stop(widget.alarmId);
    } catch (_) {}
    await TaskAlarmService.snooze(widget.taskId, minutes: 5);
    _popToRoot();
  }

  Future<void> _acceptCall() async {
    if (_closing) return;
    setState(() => _closing = true);
    _callTimeout?.cancel();
    try {
      await Alarm.stop(widget.alarmId);
    } catch (_) {}
    try {
      if (widget.onAcceptCall != null) {
        await widget.onAcceptCall!();
      } else {
        await TaskAlarmService.acceptSimulatedCall(widget.taskId);
      }
    } catch (error) {
      debugPrint('[AlarmScreen] Failed to accept simulated call: $error');
    } finally {
      _popToRoot();
    }
  }

  Future<void> _rejectCall() async {
    if (_closing) return;
    setState(() => _closing = true);
    _callTimeout?.cancel();
    try {
      final dnd = await TaskAlarmService.isDoNotDisturbActive();
      try {
        await Alarm.stop(widget.alarmId);
      } catch (_) {}
      if (widget.onRejectCall != null) {
        await widget.onRejectCall!(dnd);
      } else {
        await TaskAlarmService.refuseSimulatedCall(widget.taskId, dnd: dnd);
      }
    } catch (error) {
      debugPrint('[AlarmScreen] Failed to reject simulated call: $error');
    } finally {
      _popToRoot();
    }
  }

  String get _clockLabel =>
      '${_now.hour.toString().padLeft(2, '0')}:${_now.minute.toString().padLeft(2, '0')}';

  String get _secondsLabel => _now.second.toString().padLeft(2, '0');

  String get _dateLabel {
    final wd = _weekdays[_now.weekday - 1];
    final month = _months[_now.month - 1];
    return '$wd, ${_now.day} de $month';
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      // Locked while ringing (a choice is required); released while closing
      // so the programmatic popUntil actually removes this route.
      canPop: _closing,
      child: Scaffold(
        backgroundColor: const Color(0xFF07090F),
        body: Container(
          width: double.infinity,
          decoration: const BoxDecoration(
            gradient: RadialGradient(
              center: Alignment(0, -0.4),
              radius: 1.2,
              colors: [Color(0xFF141B33), Color(0xFF030407)],
            ),
          ),
          child: SafeArea(
            child: Column(
              children: [
                const Spacer(flex: 2),
                // ── Live clock ────────────────────────────────────────────
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _clockLabel,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 76,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 2,
                        height: 1.0,
                        fontFeatures: [FontFeature.tabularFigures()],
                      ),
                    ),
                    const SizedBox(width: 6),
                    Padding(
                      padding: const EdgeInsets.only(top: 14),
                      child: Text(
                        _secondsLabel,
                        style: TextStyle(
                          color: const Color(0xFF6366F1).withValues(alpha: 0.9),
                          fontSize: 22,
                          fontWeight: FontWeight.w700,
                          fontFeatures: [FontFeature.tabularFigures()],
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                Text(
                  _dateLabel,
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.55),
                    fontSize: 15,
                    fontWeight: FontWeight.w500,
                    letterSpacing: 0.3,
                  ),
                ),
                const Spacer(flex: 1),
                // ── Bell ──────────────────────────────────────────────────
                Container(
                  padding: const EdgeInsets.all(26),
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: const Color(0xFFEF4444).withValues(alpha: 0.12),
                    border: Border.all(
                      color: const Color(0xFFEF4444).withValues(alpha: 0.55),
                      width: 3,
                    ),
                    boxShadow: [
                      BoxShadow(
                        color: const Color(0xFFEF4444).withValues(alpha: 0.25),
                        blurRadius: 40,
                        spreadRadius: 6,
                      ),
                    ],
                  ),
                  child: Icon(
                    widget.simulatedCall
                        ? Icons.call_rounded
                        : Icons.alarm_rounded,
                    size: 64,
                    color: Color(0xFFEF4444),
                  ),
                ),
                const SizedBox(height: 24),
                Text(
                  widget.simulatedCall
                      ? 'LIGAÇÃO DO SIRIUS'
                      : 'ALARME DE TAREFA',
                  style: TextStyle(
                    color: Color(0xFFEF4444),
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 4,
                  ),
                ),
                const SizedBox(height: 12),
                if (widget.simulatedCall)
                  const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 28),
                    child: Text(
                      'Ao aceitar, o Sirius lê seu lembrete. A tarefa continua pendente até você concluí-la.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.white70, fontSize: 14),
                    ),
                  ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 32),
                  child: Text(
                    widget.title,
                    textAlign: TextAlign.center,
                    maxLines: 4,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 32,
                      fontWeight: FontWeight.w800,
                      height: 1.2,
                    ),
                  ),
                ),
                const Spacer(flex: 2),
                // ── Actions ───────────────────────────────────────────────
                if (widget.simulatedCall)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(28, 0, 28, 28),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                      children: [
                        _CallActionButton(
                          label: 'Recusar',
                          icon: Icons.call_end_rounded,
                          color: const Color(0xFFEF4444),
                          onPressed: _rejectCall,
                        ),
                        _CallActionButton(
                          label: 'Aceitar',
                          icon: Icons.call_rounded,
                          color: const Color(0xFF22C55E),
                          onPressed: _acceptCall,
                        ),
                      ],
                    ),
                  )
                else ...[
                  Padding(
                    padding: const EdgeInsets.fromLTRB(28, 0, 28, 8),
                    child: SizedBox(
                      width: double.infinity,
                      child: FilledButton.icon(
                        onPressed: _dismiss,
                        icon: const Icon(Icons.check_circle_outline, size: 26),
                        label: const Text(
                          'Dispensar',
                          style: TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        style: FilledButton.styleFrom(
                          backgroundColor: const Color(0xFF22C55E),
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(vertical: 18),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(16),
                          ),
                        ),
                      ),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(28, 0, 28, 28),
                    child: SizedBox(
                      width: double.infinity,
                      child: OutlinedButton.icon(
                        onPressed: _snooze,
                        icon: const Icon(Icons.snooze_rounded, size: 26),
                        label: const Text(
                          'Adiar 5 min',
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: Colors.white,
                          side: BorderSide(
                            color: Colors.white.withValues(alpha: 0.25),
                            width: 1.5,
                          ),
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(16),
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _CallActionButton extends StatelessWidget {
  const _CallActionButton({
    required this.label,
    required this.icon,
    required this.color,
    required this.onPressed,
  });

  final String label;
  final IconData icon;
  final Color color;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) => Semantics(
    button: true,
    label: label,
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Material(
          color: color,
          shape: const CircleBorder(),
          elevation: 8,
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onPressed,
            child: SizedBox(
              width: 76,
              height: 76,
              child: Icon(icon, size: 32, color: Colors.white),
            ),
          ),
        ),
        const SizedBox(height: 10),
        Text(
          label,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 15,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    ),
  );
}
