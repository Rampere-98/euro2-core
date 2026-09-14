import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../state.dart';
import '../widgets.dart';
import 'coin_detail.dart';

class ScanScreen extends StatefulWidget {
  const ScanScreen({super.key});

  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends State<ScanScreen> {
  Uint8List? _photo;
  Map<String, dynamic>? _result;
  bool _busy = false;
  Object? _error;

  Future<void> _pick(ImageSource source) async {
    final file = await ImagePicker().pickImage(source: source, maxWidth: 1600, imageQuality: 90);
    if (file == null) return;
    final bytes = await file.readAsBytes();
    if (!mounted) return;
    final api = context.read<AppState>().api;
    setState(() {
      _photo = bytes;
      _result = null;
      _error = null;
      _busy = true;
    });
    try {
      final r = await api.upload('/identify', bytes, 'coin.jpg');
      setState(() => _result = Map<String, dynamic>.from(r));
    } catch (e) {
      setState(() => _error = e);
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _confirm(Map<String, dynamic> candidate) async {
    final api = context.read<AppState>().api;
    try {
      await api.post('/identify/${_result!['identification_id']}/confirm',
          body: {'type_id': candidate['type']['id']});
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('¡Gracias! Tu confirmación mejora el reconocimiento.')));
      }
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final api = context.read<AppState>().api;
    final candidates = List<Map<String, dynamic>>.from(_result?['candidates'] ?? []);
    return Scaffold(
      appBar: AppBar(title: const Text('Identificar moneda')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        if (_photo != null)
          ClipRRect(
            borderRadius: BorderRadius.circular(16),
            child: Image.memory(_photo!, height: 220, fit: BoxFit.contain),
          )
        else
          Container(
            height: 220,
            decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(16),
                color: Theme.of(context).colorScheme.surfaceContainerHighest),
            child: const Center(
                child: Text('Haz una foto de la cara nacional de la moneda\n(la que tiene el dibujo del país)',
                    textAlign: TextAlign.center)),
          ),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(
            child: FilledButton.icon(
                onPressed: _busy ? null : () => _pick(ImageSource.camera),
                icon: const Icon(Icons.photo_camera),
                label: const Text('Cámara')),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: OutlinedButton.icon(
                onPressed: _busy ? null : () => _pick(ImageSource.gallery),
                icon: const Icon(Icons.photo_library),
                label: const Text('Galería')),
          ),
        ]),
        const SizedBox(height: 16),
        if (_busy) const Center(child: CircularProgressIndicator()),
        if (_error != null) ErrorBox(_error!),
        if (_result != null && candidates.isEmpty)
          const Card(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: Text('No reconozco esta moneda como una de 2 € catalogada. '
                  'Prueba con más luz, enfocando el centro de la moneda, sin el anillo de estrellas cortado.'),
            ),
          ),
        if (candidates.isNotEmpty) ...[
          Text(_result!['found_circle'] == true ? 'Moneda localizada en la foto' : 'No se localizó el contorno; se usó la foto completa',
              style: Theme.of(context).textTheme.labelMedium),
          for (final c in candidates) _CandidateCard(api: api, candidate: c, onConfirm: () => _confirm(c)),
        ],
      ]),
    );
  }
}

class _CandidateCard extends StatelessWidget {
  const _CandidateCard({required this.api, required this.candidate, required this.onConfirm});
  final dynamic api;
  final Map<String, dynamic> candidate;
  final VoidCallback onConfirm;

  @override
  Widget build(BuildContext context) {
    final type = Map<String, dynamic>.from(candidate['type']);
    final confidence = candidate['confidence'] as String;
    final scheme = Theme.of(context).colorScheme;
    final color = switch (confidence) {
      'high' => Colors.green,
      'medium' => Colors.orange,
      _ => scheme.outline,
    };
    final label = switch (confidence) {
      'high' => 'Coincidencia verificada',
      'medium' => 'Probable',
      _ => 'Parecida (sin verificar)',
    };
    return Card(
      child: Column(children: [
        TypeTile(
          api: api,
          type: type,
          trailing: Chip2(label, color: color),
          onTap: () => Navigator.of(context)
              .push(MaterialPageRoute(builder: (_) => CoinDetailScreen(typeId: type['id']))),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 8, 4),
          child: Row(children: [
            Text('puntuación ${(candidate['score'] as num).toStringAsFixed(2)}',
                style: Theme.of(context).textTheme.labelSmall),
            const Spacer(),
            TextButton(onPressed: onConfirm, child: const Text('Es esta')),
          ]),
        ),
      ]),
    );
  }
}
