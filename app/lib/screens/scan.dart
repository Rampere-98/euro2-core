import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../device.dart';
import '../navigation/swipe_back.dart';
import '../state.dart';
import '../widgets.dart';
import '../widgets/coin_visuals.dart';
import 'coin_detail.dart';
import 'crop.dart';

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
    setState(() => _photo = bytes);
    await _identify(bytes, guided: false);
  }

  /// The server locates and crops the coin on its own; `guided` means the user framed it by hand.
  Future<void> _identify(Uint8List bytes, {required bool guided}) async {
    final api = context.read<AppState>().api;
    setState(() {
      _result = null;
      _error = null;
      _busy = true;
    });
    try {
      final r = await api.upload(guided ? '/identify?guided=true' : '/identify', bytes, 'coin.jpg');
      setState(() => _result = Map<String, dynamic>.from(r));
    } catch (e) {
      setState(() => _error = e);
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _adjustCrop() async {
    final photo = _photo;
    if (photo == null) return;
    final cropped = await Navigator.of(context)
        .push<Uint8List>(SwipeBackRoute(builder: (_) => CoinCropScreen(photo: photo)));
    if (cropped != null && mounted) await _identify(cropped, guided: true);
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
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Column(children: [
            Center(
              child: GoldRing(
                size: 236,
                width: 4,
                spin: _busy,
                child: _photo != null
                    ? Image.memory(_photo!, fit: BoxFit.cover, gaplessPlayback: true, cacheHeight: 480)
                    : Container(
                        color: Theme.of(context).colorScheme.surfaceContainerHigh,
                        child: Icon(Icons.euro, size: 96,
                            color: Theme.of(context).colorScheme.primary.withValues(alpha: .35)),
                      ),
              ),
            ),
            const SizedBox(height: 18),
            Text(_photo == null ? 'Identifica cualquier moneda de 2 \u20ac' : (_busy ? 'Analizando\u2026' : 'Foto analizada'),
                style: Theme.of(context).textTheme.headlineSmall, textAlign: TextAlign.center),
            const SizedBox(height: 6),
            Text(
              _photo == null
                  ? 'Haz una foto a la cara nacional (la del dibujo del pa\u00eds). La moneda se recorta sola.'
                  : 'Comprueba el recorte y confirma la moneda para mejorar el reconocimiento.',
              style: Theme.of(context).textTheme.bodySmall,
              textAlign: TextAlign.center,
            ),
          ]),
        ),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(
            child: FilledButton.icon(
                onPressed: _busy ? null : () => _pick(ImageSource.camera),
                icon: const Icon(Icons.photo_camera),
                label: Text(Device.isTouch ? 'Hacer foto' : 'Cámara')),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: OutlinedButton.icon(
                onPressed: _busy ? null : () => _pick(ImageSource.gallery),
                icon: const Icon(Icons.photo_library),
                label: Text(Device.isTouch ? 'Galería' : 'Elegir imagen')),
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
                  'Prueba con más luz, enfocando el centro de la moneda, o ajusta el recorte a mano.'),
            ),
          ),
        if (_result != null) _CropCheck(api: api, result: _result!, onAdjust: _busy ? null : _adjustCrop),
        for (final c in candidates) _CandidateCard(api: api, candidate: c, onConfirm: () => _confirm(c)),
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
              .push(SwipeBackRoute(builder: (_) => CoinDetailScreen(typeId: type['id']))),
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

/// Shows the square the server actually matched, so a bad automatic crop is obvious at a glance,
/// with the manual framing as the escape hatch.
class _CropCheck extends StatelessWidget {
  const _CropCheck({required this.api, required this.result, required this.onAdjust});
  final dynamic api;
  final Map<String, dynamic> result;
  final VoidCallback? onAdjust;

  @override
  Widget build(BuildContext context) {
    final located = result['found_circle'] == true;
    final cropUrl = result['crop_url'] as String?;
    final text = Theme.of(context).textTheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(children: [
          if (cropUrl != null)
            ClipRRect(
              borderRadius: BorderRadius.circular(40),
              child: Image.network(api.imageUrl(cropUrl), width: 80, height: 80, fit: BoxFit.cover,
                  errorBuilder: (_, _, _) => const SizedBox(width: 80, height: 80)),
            ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(located ? 'Moneda localizada automáticamente' : 'Recorte automático (contorno no claro)',
                  style: text.titleSmall),
              Text('Esto es lo que se ha analizado. Si no es la moneda completa, ajústalo.',
                  style: text.bodySmall),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton.icon(
                    onPressed: onAdjust,
                    icon: const Icon(Icons.crop, size: 18),
                    label: const Text('Ajustar recorte')),
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}
