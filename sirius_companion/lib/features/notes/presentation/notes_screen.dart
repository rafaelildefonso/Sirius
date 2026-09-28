import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/storage/database/database.dart';
import '../../../core/storage/repositories/note_repository.dart';
import '../application/note_sync_service.dart';
import 'note_editor_screen.dart';

class NotesScreen extends ConsumerStatefulWidget {
  const NotesScreen({super.key});

  @override
  ConsumerState<NotesScreen> createState() => _NotesScreenState();
}

class _NotesScreenState extends ConsumerState<NotesScreen> {
  late final NoteRepository _noteRepo;

  @override
  void initState() {
    super.initState();
    _noteRepo = NoteRepository(AppDatabase());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF07090F),
      appBar: AppBar(
        title: const Text('Anotações'),
        backgroundColor: const Color(0xFF07090F),
      ),
      body: StreamBuilder<List<Note>>(
        stream: _noteRepo.watchAll(),
        builder: (context, snapshot) {
          final notes = snapshot.data ?? [];
          if (notes.isEmpty) {
            return const Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.note_add_outlined,
                    size: 48,
                    color: Color(0xFF5E6A7E),
                  ),
                  SizedBox(height: 12),
                  Text(
                    'Nenhuma anotação',
                    style: TextStyle(color: Color(0xFF5E6A7E), fontSize: 16),
                  ),
                  SizedBox(height: 4),
                  Text(
                    'Toque + para criar',
                    style: TextStyle(color: Color(0xFF5E6A7E), fontSize: 13),
                  ),
                ],
              ),
            );
          }
          return ListView.builder(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            itemCount: notes.length,
            itemBuilder: (context, index) => _NoteTile(
              note: notes[index],
              onTap: () => _editNote(notes[index]),
              onDelete: () => _deleteNote(notes[index]),
              onRetry:
                  notes[index].classificationError != null &&
                      notes[index].classificationStatus != 'completed'
                  ? () => _retryClassification(notes[index])
                  : null,
            ),
          );
        },
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: _createNote,
        backgroundColor: const Color(0xFF6366F1),
        child: const Icon(Icons.add, color: Colors.white),
      ),
    );
  }

  void _createNote() {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const NoteEditorScreen()),
    );
  }

  void _editNote(Note note) {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => NoteEditorScreen(note: note)),
    );
  }

  Future<void> _retryClassification(Note note) async {
    await _noteRepo.updateClassification(
      id: note.id,
      status: 'classifying',
      error: null,
    );
    await classifyNoteInBackground(note.id);
  }

  Future<void> _deleteNote(Note note) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0D1117),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text(
          'Excluir anotação?',
          style: TextStyle(color: Colors.white),
        ),
        content: Text(
          'Remover "${note.title.isNotEmpty ? note.title : 'anotação'}"?',
          style: const TextStyle(color: Color(0xFF9CA3AF)),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text(
              'Cancelar',
              style: TextStyle(color: Color(0xFF9CA3AF)),
            ),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFEF4444),
            ),
            child: const Text('Excluir'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await _noteRepo.delete(note.id);
    }
  }
}

class _NoteTile extends StatelessWidget {
  final Note note;
  final VoidCallback onTap;
  final VoidCallback onDelete;
  final VoidCallback? onRetry;

  const _NoteTile({
    required this.note,
    required this.onTap,
    required this.onDelete,
    this.onRetry,
  });

  static const _categoryIcons = {
    'curso': Icons.school,
    'ideia': Icons.lightbulb,
    'curiosidade': Icons.search,
    'link': Icons.link,
    'geral': Icons.note,
    'lista': Icons.checklist,
    'meta': Icons.flag,
  };

  static const _categoryColors = {
    'curso': Color(0xFF6366F1),
    'ideia': Color(0xFFFBBF24),
    'curiosidade': Color(0xFF22C55E),
    'link': Color(0xFF3B82F6),
    'geral': Color(0xFF9CA3AF),
    'lista': Color(0xFFF472B6),
    'meta': Color(0xFFEF4444),
  };

  static const _categoryLabels = {
    'curso': 'Curso',
    'ideia': 'Ideia',
    'curiosidade': 'Curiosidade',
    'link': 'Link',
    'geral': 'Geral',
    'lista': 'Lista',
    'meta': 'Meta',
  };

  @override
  Widget build(BuildContext context) {
    final icon = _categoryIcons[note.category] ?? Icons.note;
    final color = _categoryColors[note.category] ?? const Color(0xFF9CA3AF);
    final label = _categoryLabels[note.category] ?? note.category;
    final hasAttachments =
        note.attachmentPaths != null &&
        (note.attachmentPaths as String).isNotEmpty &&
        note.attachmentPaths != '[]';

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(14),
        margin: const EdgeInsets.only(bottom: 8),
        decoration: BoxDecoration(
          color: const Color(0xFFFFFFFF).withOpacity(0.04),
          border: Border.all(color: const Color(0xFFFFFFFF).withOpacity(0.08)),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                color: color.withOpacity(0.15),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(icon, color: color, size: 20),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          note.title.isNotEmpty ? note.title : '(Sem título)',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                            color: note.title.isNotEmpty
                                ? Colors.white
                                : const Color(0xFF5E6A7E),
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      if (hasAttachments) ...[
                        const SizedBox(width: 4),
                        const Icon(
                          Icons.attach_file,
                          size: 14,
                          color: Color(0xFF5E6A7E),
                        ),
                      ],
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(
                    label,
                    style: TextStyle(
                      fontSize: 11,
                      color: color.withOpacity(0.8),
                    ),
                  ),
                  if (note.classificationStatus != 'completed') ...[
                    const SizedBox(height: 2),
                    Text(
                      note.classificationStatus == 'classifying'
                          ? 'Classificando com IA...'
                          : note.classificationStatus == 'fallback_pending'
                          ? 'Aguardando classificação no PC...'
                          : note.classificationStatus == 'failed'
                          ? 'Falha ao classificar — toque para tentar novamente'
                          : 'Classificação pendente...',
                      style: TextStyle(
                        fontSize: 10,
                        color: note.classificationStatus == 'failed'
                            ? const Color(0xFFFCA5A5)
                            : const Color(0xFF818CF8),
                      ),
                    ),
                    if (onRetry != null) ...[
                      const SizedBox(height: 2),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: TextButton.icon(
                          onPressed: onRetry,
                          icon: const Icon(Icons.refresh, size: 13),
                          label: const Text('Tentar novamente'),
                          style: TextButton.styleFrom(
                            minimumSize: Size.zero,
                            padding: EdgeInsets.zero,
                            tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                            foregroundColor: const Color(0xFFFCA5A5),
                            textStyle: const TextStyle(fontSize: 10),
                          ),
                        ),
                      ),
                    ],
                  ],
                  if (note.content.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text(
                      note.content,
                      style: const TextStyle(
                        fontSize: 12,
                        color: Color(0xFF9CA3AF),
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: 8),
            _SyncBadge(status: note.syncStatus),
            IconButton(
              icon: const Icon(
                Icons.delete_outline,
                color: Color(0xFFEF4444),
                size: 18,
              ),
              onPressed: onDelete,
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(),
            ),
          ],
        ),
      ),
    );
  }
}

class _SyncBadge extends StatelessWidget {
  final String status;
  const _SyncBadge({required this.status});

  @override
  Widget build(BuildContext context) {
    switch (status) {
      case 'synced':
        return const Icon(
          Icons.check_circle,
          size: 16,
          color: Color(0xFF22C55E),
        );
      case 'syncing':
        return const SizedBox(
          width: 16,
          height: 16,
          child: CircularProgressIndicator(
            strokeWidth: 2,
            color: Color(0xFF6366F1),
          ),
        );
      case 'error':
        return const Icon(
          Icons.error_outline,
          size: 16,
          color: Color(0xFFEF4444),
        );
      default: // pending
        return const Icon(Icons.schedule, size: 16, color: Color(0xFF5E6A7E));
    }
  }
}
