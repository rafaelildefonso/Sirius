import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:uuid/uuid.dart';
import '../../../core/storage/database/database.dart';
import '../../../core/storage/repositories/note_repository.dart';
import '../application/note_sync_service.dart';

class NoteEditorScreen extends StatefulWidget {
  final Note? note;
  const NoteEditorScreen({super.key, this.note});

  @override
  State<NoteEditorScreen> createState() => _NoteEditorScreenState();
}

class _NoteEditorScreenState extends State<NoteEditorScreen> {
  late final TextEditingController _titleController;
  late final TextEditingController _contentController;
  late final NoteRepository _noteRepo;
  String _selectedCategory = 'geral';
  List<String> _attachmentPaths = [];
  bool _classifying = false;
  String? _aiSummary;
  String? _aiTags;
  String? _classificationError;
  bool _saving = false;

  static const _categories = [
    ('curso', 'Curso / Tutorial', Icons.school),
    ('ideia', 'Ideia', Icons.lightbulb),
    ('curiosidade', 'Curiosidade / Pesquisa', Icons.search),
    ('link', 'Link / Referência', Icons.link),
    ('geral', 'Anotação Geral', Icons.note),
    ('lista', 'Lista / Checklist', Icons.checklist),
    ('meta', 'Meta / Objetivo', Icons.flag),
  ];

  bool get _isEditing => widget.note != null;

  @override
  void initState() {
    super.initState();
    _titleController = TextEditingController(text: widget.note?.title ?? '');
    _contentController = TextEditingController(
      text: widget.note?.content ?? '',
    );
    _noteRepo = NoteRepository(AppDatabase());
    _selectedCategory = widget.note?.category ?? 'geral';
    _aiSummary = widget.note?.aiSummary;
    _aiTags = widget.note?.aiTags;
    _classificationError = widget.note?.classificationError;
    _classifying = widget.note?.classificationStatus == 'classifying';
    if (widget.note?.attachmentPaths != null) {
      try {
        _attachmentPaths = List<String>.from(
          jsonDecode(widget.note!.attachmentPaths!),
        );
      } catch (_) {}
    }
  }

  @override
  void dispose() {
    _titleController.dispose();
    _contentController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF07090F),
      appBar: AppBar(
        title: Text(_isEditing ? 'Editar Anotação' : 'Nova Anotação'),
        backgroundColor: const Color(0xFF07090F),
        actions: [
          if (_isEditing && _aiSummary != null)
            IconButton(
              icon: const Icon(Icons.auto_awesome, size: 20),
              onPressed: _showAiInfo,
              tooltip: 'Info IA',
            ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _titleController,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 18,
                fontWeight: FontWeight.w600,
              ),
              decoration: InputDecoration(
                hintText: 'Título (opcional)',
                hintStyle: const TextStyle(color: Color(0xFF5E6A7E)),
                border: InputBorder.none,
                contentPadding: EdgeInsets.zero,
              ),
            ),
            const SizedBox(height: 8),
            // Category chips
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: _categories.map((c) {
                final isSelected = _selectedCategory == c.$1;
                final color = isSelected
                    ? const Color(0xFF6366F1)
                    : const Color(0xFFFFFFFF).withOpacity(0.08);
                return ChoiceChip(
                  label: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        c.$3,
                        size: 14,
                        color: isSelected
                            ? Colors.white
                            : const Color(0xFF9CA3AF),
                      ),
                      const SizedBox(width: 4),
                      Text(
                        c.$2,
                        style: TextStyle(
                          color: isSelected
                              ? Colors.white
                              : const Color(0xFF9CA3AF),
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                  selected: isSelected,
                  onSelected: (_) => setState(() => _selectedCategory = c.$1),
                  backgroundColor: const Color(0xFFFFFFFF).withOpacity(0.05),
                  selectedColor: color,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                  side: BorderSide(
                    color: isSelected
                        ? const Color(0xFF6366F1)
                        : const Color(0xFFFFFFFF).withOpacity(0.1),
                  ),
                );
              }).toList(),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _contentController,
              style: const TextStyle(color: Colors.white, fontSize: 15),
              maxLines: null,
              minLines: 10,
              keyboardType: TextInputType.multiline,
              decoration: InputDecoration(
                hintText: 'Escreva sua anotação aqui...',
                hintStyle: const TextStyle(color: Color(0xFF5E6A7E)),
                border: InputBorder.none,
                contentPadding: EdgeInsets.zero,
              ),
            ),
            const SizedBox(height: 16),
            // Attachments section
            if (_attachmentPaths.isNotEmpty) ...[
              const Text(
                'Anexos',
                style: TextStyle(
                  color: Color(0xFF9CA3AF),
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: _attachmentPaths.map((path) {
                  return Stack(
                    clipBehavior: Clip.none,
                    children: [
                      ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: Image.file(
                          File(path),
                          width: 80,
                          height: 80,
                          fit: BoxFit.cover,
                          errorBuilder: (_, __, ___) => Container(
                            width: 80,
                            height: 80,
                            decoration: BoxDecoration(
                              color: const Color(0xFFFFFFFF).withOpacity(0.05),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: const Icon(
                              Icons.image_not_supported,
                              color: Color(0xFF5E6A7E),
                            ),
                          ),
                        ),
                      ),
                      Positioned(
                        top: -4,
                        right: -4,
                        child: GestureDetector(
                          onTap: () =>
                              setState(() => _attachmentPaths.remove(path)),
                          child: Container(
                            width: 20,
                            height: 20,
                            decoration: const BoxDecoration(
                              color: Color(0xFFEF4444),
                              shape: BoxShape.circle,
                            ),
                            child: const Icon(
                              Icons.close,
                              size: 12,
                              color: Colors.white,
                            ),
                          ),
                        ),
                      ),
                    ],
                  );
                }).toList(),
              ),
              const SizedBox(height: 16),
            ],
            // AI section
            if (_classifying) ...[
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF6366F1).withOpacity(0.1),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: const Row(
                  children: [
                    SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Color(0xFF6366F1),
                      ),
                    ),
                    SizedBox(width: 10),
                    Text(
                      'Classificando com IA...',
                      style: TextStyle(color: Color(0xFF6366F1), fontSize: 13),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
            ],
            if (_aiSummary != null && !_classifying) ...[
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF22C55E).withOpacity(0.08),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: const Color(0xFF22C55E).withOpacity(0.2),
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Row(
                      children: [
                        Icon(
                          Icons.auto_awesome,
                          size: 14,
                          color: Color(0xFF22C55E),
                        ),
                        SizedBox(width: 6),
                        Text(
                          'Classificação IA',
                          style: TextStyle(
                            color: Color(0xFF22C55E),
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      _aiSummary!,
                      style: const TextStyle(
                        color: Color(0xFF9CA3AF),
                        fontSize: 13,
                      ),
                    ),
                    if (_aiTags != null) ...[
                      const SizedBox(height: 6),
                      Wrap(
                        spacing: 4,
                        runSpacing: 4,
                        children: _parseTags(_aiTags!)
                            .map(
                              (tag) => Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 8,
                                  vertical: 2,
                                ),
                                decoration: BoxDecoration(
                                  color: const Color(
                                    0xFF22C55E,
                                  ).withOpacity(0.1),
                                  borderRadius: BorderRadius.circular(6),
                                ),
                                child: Text(
                                  tag,
                                  style: const TextStyle(
                                    color: Color(0xFF22C55E),
                                    fontSize: 11,
                                  ),
                                ),
                              ),
                            )
                            .toList(),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 16),
            ],
            if (_classificationError != null &&
                !_classifying &&
                _isEditing) ...[
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFFEF4444).withOpacity(0.08),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'A classificação falhou: $_classificationError',
                      style: const TextStyle(
                        color: Color(0xFFFCA5A5),
                        fontSize: 12,
                      ),
                    ),
                    const SizedBox(height: 8),
                    OutlinedButton.icon(
                      onPressed: () async {
                        setState(() {
                          _classifying = true;
                          _classificationError = null;
                        });
                        await classifyNoteInBackground(widget.note!.id);
                        if (mounted) {
                          final updated = await _noteRepo.getById(
                            widget.note!.id,
                          );
                          setState(() {
                            _classifying = false;
                            _classificationError = updated?.classificationError;
                            _aiSummary = updated?.aiSummary;
                            _aiTags = updated?.aiTags;
                          });
                        }
                      },
                      icon: const Icon(Icons.refresh, size: 16),
                      label: const Text('Classificar novamente'),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
            ],
            // A classificação é disparada automaticamente depois de salvar.
            // Aqui fica apenas a ação de anexar uma imagem.
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton.icon(
                onPressed: _classifying ? null : _addAttachment,
                icon: const Icon(Icons.camera_alt, size: 18),
                label: const Text('Imagem'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: const Color(0xFF9CA3AF),
                  side: BorderSide(
                    color: const Color(0xFFFFFFFF).withOpacity(0.15),
                  ),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 20,
                    vertical: 12,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 20),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: _saving ? null : _save,
                icon: _saving
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Icon(Icons.save, size: 20),
                label: Text(_isEditing ? 'ATUALIZAR' : 'SALVAR'),
                style: FilledButton.styleFrom(
                  backgroundColor: const Color(0xFF6366F1),
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                  textStyle: const TextStyle(
                    fontWeight: FontWeight.w700,
                    letterSpacing: 1,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  List<String> _parseTags(String tagsJson) {
    try {
      final decoded = jsonDecode(tagsJson);
      if (decoded is List) return decoded.cast<String>();
    } catch (_) {}
    return [];
  }

  Future<void> _addAttachment() async {
    final picker = ImagePicker();
    final picked = await picker.pickImage(source: ImageSource.gallery);
    if (picked == null) return;

    final appDir = await getApplicationDocumentsDirectory();
    final notesDir = Directory('${appDir.path}/notes/attachments');
    if (!await notesDir.exists()) {
      await notesDir.create(recursive: true);
    }

    final fileName = '${const Uuid().v4()}_${picked.name}';
    final savedFile = await File(
      picked.path,
    ).copy('${notesDir.path}/$fileName');
    setState(() => _attachmentPaths.add(savedFile.path));
  }

  Future<void> _save() async {
    final content = _contentController.text.trim();
    if (content.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('O conteúdo não pode estar vazio')),
      );
      return;
    }

    setState(() => _saving = true);

    try {
      final title = _titleController.text.trim();
      int totalBytes = utf8.encode(content).length;
      for (final path in _attachmentPaths) {
        try {
          final file = File(path);
          if (await file.exists()) {
            totalBytes += await file.length();
          }
        } catch (_) {}
      }

      late final int noteId;
      if (_isEditing) {
        await _noteRepo.updateNote(
          id: widget.note!.id,
          title: title,
          content: content,
          category: _selectedCategory,
          aiSummary: _aiSummary,
          aiTags: _aiTags,
          attachmentPaths: _attachmentPaths,
          totalAttachmentBytes: totalBytes,
        );
        noteId = widget.note!.id;
      } else {
        noteId = await _noteRepo.create(
          title: title,
          content: content,
          category: _selectedCategory,
          aiSummary: _aiSummary,
          aiTags: _aiTags,
          attachmentPaths: _attachmentPaths,
          totalAttachmentBytes: totalBytes,
        );
      }

      // Persist first, then classify outside this route.  The Notes stream
      // receives the status/result even after the editor is closed.
      unawaited(classifyNoteInBackground(noteId));

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              _isEditing ? 'Anotação atualizada' : 'Anotação salva',
            ),
            backgroundColor: const Color(0xFF22C55E),
          ),
        );
        Navigator.pop(context);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Erro: $e'),
            backgroundColor: const Color(0xFFEF4444),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  void _showAiInfo() {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF0D1117),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(Icons.auto_awesome, color: Color(0xFF22C55E), size: 20),
                SizedBox(width: 8),
                Text(
                  'Classificação IA',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            if (_aiSummary != null) ...[
              const Text(
                'Resumo',
                style: TextStyle(color: Color(0xFF9CA3AF), fontSize: 12),
              ),
              const SizedBox(height: 4),
              Text(
                _aiSummary!,
                style: const TextStyle(color: Colors.white, fontSize: 14),
              ),
              const SizedBox(height: 12),
            ],
            if (_aiTags != null) ...[
              const Text(
                'Tags',
                style: TextStyle(color: Color(0xFF9CA3AF), fontSize: 12),
              ),
              const SizedBox(height: 4),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: _parseTags(_aiTags!)
                    .map(
                      (tag) => Chip(
                        label: Text(
                          tag,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 12,
                          ),
                        ),
                        backgroundColor: const Color(
                          0xFF6366F1,
                        ).withOpacity(0.3),
                        materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        visualDensity: VisualDensity.compact,
                      ),
                    )
                    .toList(),
              ),
            ],
            const SizedBox(height: 20),
          ],
        ),
      ),
    );
  }
}
