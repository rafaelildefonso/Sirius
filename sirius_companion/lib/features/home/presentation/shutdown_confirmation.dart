import 'package:flutter/material.dart';

Future<bool> confirmComputerShutdown(BuildContext context) async {
  return await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Desligar computador?'),
          content: const Text(
            'O computador pareado será desligado. Deseja continuar?',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: const Text('Cancelar'),
            ),
            FilledButton.icon(
              onPressed: () => Navigator.of(dialogContext).pop(true),
              icon: const Icon(Icons.power_settings_new),
              label: const Text('Desligar computador'),
              style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFFB91C1C),
              ),
            ),
          ],
        ),
      ) ??
      false;
}
