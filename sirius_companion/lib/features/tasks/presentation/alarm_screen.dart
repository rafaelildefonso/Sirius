import 'package:flutter/material.dart';

import '../task_alarm_service.dart';

/// Full-screen silent reminder shown over the lockscreen when a task fires:
/// task name + a single dismiss button (no sound, vibration only).
class AlarmScreen extends StatelessWidget {
  final String taskId;
  final String title;

  const AlarmScreen({
    super.key,
    required this.taskId,
    required this.title,
  });

  Future<void> _dismiss(BuildContext context) async {
    await TaskAlarmService.markDone(taskId);
    if (context.mounted) {
      Navigator.of(context).popUntil((route) => route.isFirst);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
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
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(28),
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: const Color(0xFF6366F1).withValues(alpha: 0.15),
                  border: Border.all(
                    color: const Color(0xFF6366F1).withValues(alpha: 0.5),
                    width: 3,
                  ),
                ),
                child: const Icon(
                  Icons.task_alt_rounded,
                  size: 72,
                  color: Color(0xFF6366F1),
                ),
              ),
              const SizedBox(height: 28),
              const Text(
                'LEMBRETE',
                style: TextStyle(
                  color: Color(0xFF6366F1),
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
                child: SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: () => _dismiss(context),
                    icon: const Icon(Icons.check_circle_outline, size: 26),
                    label: const Text(
                      'Dispensar',
                      style: TextStyle(
                          fontSize: 20, fontWeight: FontWeight.w700),
                    ),
                    style: FilledButton.styleFrom(
                      backgroundColor: const Color(0xFF6366F1),
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 18),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(16),
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
