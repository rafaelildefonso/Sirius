import 'package:flutter_test/flutter_test.dart';
import 'package:sirius_companion/features/tasks/simulated_call_policy.dart';

void main() {
  group('SimulatedCallPolicy', () {
    test('allows a second and third attempt after explicit refusal', () {
      expect(
        SimulatedCallPolicy.retryAfterRefusal(refusals: 1, dnd: false),
        isTrue,
      );
      expect(
        SimulatedCallPolicy.retryAfterRefusal(refusals: 2, dnd: false),
        isTrue,
      );
      expect(
        SimulatedCallPolicy.retryAfterRefusal(refusals: 3, dnd: false),
        isFalse,
      );
    });

    test('DND permits one attempt and prevents retry after refusal', () {
      expect(
        SimulatedCallPolicy.retryAfterRefusal(refusals: 1, dnd: true),
        isFalse,
      );
    });

    test('missed calls do not enter the retry path', () {
      expect(SimulatedCallPolicy.retryAfterMissedCall, isFalse);
      expect(
        SimulatedCallPolicy.ringScreenDuration,
        const Duration(seconds: 30),
      );
    });

    test('acceptance speaks only and does not complete the task', () {
      expect(SimulatedCallPolicy.completeTaskOnAccept, isFalse);
      final reminder = SimulatedCallPolicy.reminderText(
        title: 'Consulta com a dentista',
        dueAt: DateTime(2026, 11, 15, 9, 5),
        notes: 'Levar os exames',
      );
      expect(reminder, contains('Consulta com a dentista'));
      expect(reminder, contains('15/11, às 09:05'));
      expect(reminder, contains('Levar os exames'));
    });

    test('retry interval is finite and configured to five minutes', () {
      expect(SimulatedCallPolicy.retryInterval, const Duration(minutes: 5));
    });

    test('missing full-screen permission falls back to a notification', () {
      final hint = SimulatedCallPolicy.alertCapabilityHint({
        'notifications': true,
        'fullScreen': false,
        'exactAlarm': true,
      });
      expect(hint, contains('notificação para tocar'));
    });

    test('missing notification permission is explained', () {
      final hint = SimulatedCallPolicy.alertCapabilityHint({
        'notifications': false,
        'fullScreen': false,
        'exactAlarm': false,
      });
      expect(hint, contains('notificações estão bloqueadas'));
    });
  });
}
