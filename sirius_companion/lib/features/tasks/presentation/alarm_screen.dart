import 'package:flutter/material.dart';

import '../task_alarm_service.dart';

/// Full-screen alarm page shown over the lockscreen when a task fires.
class AlarmScreen extends StatelessWidget {
  final String taskId;
  final String title;

  const AlarmScreen({
    super.key,
    required this.taskId,
    required this.title,
  });

  Future<void> _resolve(BuildContext context, bool done) async {
    if (done) {
      await TaskAlarmService.markDone(taskId);
    } else {
      await TaskAlarmService.snooze(taskId, minutes: 5);
    }
    if (context.mounted) {
      Navigator.of(context).popUntil((route) => route.isFirst);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF1A0505),
      body: Container(
        width: double.infinity,
        decoration: const BoxDecoration(
          gradient: RadialGradient(
            center: Alignment(0, -0.4),
            radius: 1.2,
            colors: [Color(0xFF3B0D0D), Color(0xFF0A0203)],
          ),
        ),
        child: SafeArea(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(28),
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: const Color(0xFFEF4444).withOpacity(0.15),
                  border: Border.all(
                    color: const Color(0xFFEF4444).withOpacity(0.5),
                    width: 3,
                  ),
                ),
                child: const Icon(
                  Icons.alarm_rounded,
                  size: 72,
                  color: Color(0xFFEF4444),
                ),
              ),
              const SizedBox(height: 28),
              const Text(
                'ESTÁ NA HORA!',
                style: TextStyle(
                  color: Color(0xFFEF4444),
                  fontSize: 18,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 4,
                ),
              ),
              const SizedBox(height: 16),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 32),
                child: Text(
                  title,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 34,
                    fontWeight: FontWeight.w800,
                    height: 1.2,
                  ),
                ),
              ),
              const SizedBox(height: 64),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 40),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    FilledButton.icon(
                      onPressed: () => _resolve(context, true),
                      icon: const Icon(Icons.check_circle_outline, size: 26),
                      label: const Text(
                        'Feito',
                        style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
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
                    const SizedBox(height: 14),
                    OutlinedButton.icon(
                      onPressed: () => _resolve(context, false),
                      icon: const Icon(Icons.snooze_rounded, size: 26),
                      label: const Text(
                        'Adiar 5 min',
                        style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                      ),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: const Color(0xFFFBBF24),
                        side: const BorderSide(color: Color(0xFFFBBF24), width: 2),
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(16),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
