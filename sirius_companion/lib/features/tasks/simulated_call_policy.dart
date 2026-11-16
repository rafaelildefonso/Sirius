/// Shared defaults and decisions for the simulated call flow. Routines can
/// use the same retry and quiet-mode rules when their screen is introduced.
class SimulatedCallPolicy {
  const SimulatedCallPolicy._();

  static const retryInterval = Duration(minutes: 5);
  static const maxAttempts = 3;
  static const ringScreenDuration = Duration(seconds: 30);

  /// Missed calls do not retry. A refusal retries only outside DND and while
  /// fewer than three total attempts have been explicitly refused.
  static bool retryAfterRefusal({required int refusals, required bool dnd}) =>
      !dnd && refusals < maxAttempts;

  /// Accepting speaks the reminder only; it never marks the task complete.
  static const bool completeTaskOnAccept = false;

  static const bool retryAfterMissedCall = false;

  static String reminderText({
    required String title,
    DateTime? dueAt,
    String? notes,
  }) {
    final text = StringBuffer('Olá. Este é um lembrete do Sirius. $title.');
    if (dueAt != null) {
      text.write(
        ' Agendado para ${dueAt.day}/${dueAt.month}, às '
        '${dueAt.hour.toString().padLeft(2, '0')}:${dueAt.minute.toString().padLeft(2, '0')}.',
      );
    }
    if (notes?.trim().isNotEmpty == true) text.write(' ${notes!.trim()}');
    return text.toString();
  }

  static String alertCapabilityHint(Map<String, bool> capabilities) {
    if (capabilities['notifications'] != true) {
      return 'As notificações estão bloqueadas. Ative-as nas configurações do Android para receber o alerta.';
    }
    if (capabilities['fullScreen'] != true) {
      return 'O Android não permite abrir a tela de chamada automaticamente; você receberá uma notificação para tocar.';
    }
    if (capabilities['exactAlarm'] != true) {
      return 'O alarme exato está indisponível. O Android pode entregar a notificação com atraso.';
    }
    return 'A chamada abre no app; se a tela cheia estiver indisponível, chega uma notificação para tocar.';
  }
}
