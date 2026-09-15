import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

/// Manual framing, used only when the automatic crop got it wrong: the user pans and zooms the
/// photo until the coin fills the fixed circle, and the square around that circle is rendered to
/// a PNG (at most [outputSide] px) that the server matches as-is (`guided=true`).
class CoinCropScreen extends StatefulWidget {
  const CoinCropScreen({super.key, required this.photo});
  final Uint8List photo;

  static const outputSide = 640;
  static const guideRatio = 0.42; // circle radius as a fraction of the viewport side
  static const rimMargin = 1.08; // same margin the server keeps around the rim

  @override
  State<CoinCropScreen> createState() => _CoinCropScreenState();
}

class _CoinCropScreenState extends State<CoinCropScreen> {
  final _controller = TransformationController();
  ui.Image? _image;
  double _viewport = 0; // side of the square viewport, in logical pixels
  double _fitScale = 1; // image pixels -> logical pixels so the photo covers the viewport
  bool _rendering = false;

  @override
  void initState() {
    super.initState();
    _decode();
  }

  Future<void> _decode() async {
    final codec = await ui.instantiateImageCodec(widget.photo);
    final frame = await codec.getNextFrame();
    if (mounted) setState(() => _image = frame.image);
  }

  @override
  void dispose() {
    _controller.dispose();
    _image?.dispose();
    super.dispose();
  }

  void _layout(double side) {
    if (_image == null || side == _viewport) return;
    _viewport = side;
    _fitScale = side / (_image!.width < _image!.height ? _image!.width : _image!.height);
    final w = _image!.width * _fitScale, h = _image!.height * _fitScale;
    _controller.value = Matrix4.translationValues(-(w - side) / 2, -(h - side) / 2, 0);
  }

  /// The square around the guide circle, in image pixels.
  Rect _cropRect() {
    final half = _viewport * CoinCropScreen.guideRatio * CoinCropScreen.rimMargin;
    final centre = Offset(_viewport / 2, _viewport / 2);
    final inverse = Matrix4.inverted(_controller.value);
    final tl = MatrixUtils.transformPoint(inverse, centre - Offset(half, half)) / _fitScale;
    final br = MatrixUtils.transformPoint(inverse, centre + Offset(half, half)) / _fitScale;
    final bounds = Rect.fromLTWH(0, 0, _image!.width.toDouble(), _image!.height.toDouble());
    return Rect.fromPoints(tl, br).intersect(bounds);
  }

  Future<void> _use() async {
    final image = _image;
    if (image == null || _rendering) return;
    setState(() => _rendering = true);
    try {
      final src = _cropRect();
      final side = src.shortestSide.clamp(64, CoinCropScreen.outputSide).round();
      final recorder = ui.PictureRecorder();
      Canvas(recorder).drawImageRect(
        image,
        src,
        Rect.fromLTWH(0, 0, side.toDouble(), side.toDouble()),
        Paint()..filterQuality = FilterQuality.high,
      );
      final rendered = await recorder.endRecording().toImage(side, side);
      final png = await rendered.toByteData(format: ui.ImageByteFormat.png);
      rendered.dispose();
      if (!mounted) return;
      Navigator.of(context).pop(png!.buffer.asUint8List());
    } finally {
      if (mounted) setState(() => _rendering = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final image = _image;
    return Scaffold(
      appBar: AppBar(title: const Text('Ajustar recorte')),
      body: image == null
          ? const Center(child: CircularProgressIndicator())
          : Column(children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 12, 16, 8),
                child: Text('Mueve y amplía la foto hasta que la moneda llene el círculo.',
                    textAlign: TextAlign.center),
              ),
              Expanded(
                child: LayoutBuilder(builder: (context, constraints) {
                  final side = [constraints.maxWidth, constraints.maxHeight, 480.0]
                      .reduce((a, b) => a < b ? a : b);
                  _layout(side);
                  return Center(
                    child: SizedBox(
                      width: side,
                      height: side,
                      child: Stack(fit: StackFit.expand, children: [
                        InteractiveViewer(
                          transformationController: _controller,
                          constrained: false,
                          minScale: 1,
                          maxScale: 8,
                          child: SizedBox(
                            width: image.width * _fitScale,
                            height: image.height * _fitScale,
                            child: RawImage(image: image, fit: BoxFit.fill),
                          ),
                        ),
                        IgnorePointer(
                          child: CustomPaint(
                              painter: _GuidePainter(
                                  Theme.of(context).colorScheme.primary)),
                        ),
                      ]),
                    ),
                  );
                }),
              ),
              Padding(
                padding: const EdgeInsets.all(16),
                child: Row(children: [
                  Expanded(
                    child: OutlinedButton(
                        onPressed: () => Navigator.of(context).pop(),
                        child: const Text('Cancelar')),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton.icon(
                        onPressed: _rendering ? null : _use,
                        icon: const Icon(Icons.check),
                        label: const Text('Usar este recorte')),
                  ),
                ]),
              ),
            ]),
    );
  }
}

class _GuidePainter extends CustomPainter {
  _GuidePainter(this.color);
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final centre = size.center(Offset.zero);
    final radius = size.shortestSide * CoinCropScreen.guideRatio;
    final hole = Path()..addOval(Rect.fromCircle(center: centre, radius: radius));
    final outside = Path.combine(
        PathOperation.difference, Path()..addRect(Offset.zero & size), hole);
    canvas.drawPath(outside, Paint()..color = Colors.black.withValues(alpha: 0.55));
    canvas.drawCircle(
        centre,
        radius,
        Paint()
          ..color = color
          ..style = PaintingStyle.stroke
          ..strokeWidth = 3);
  }

  @override
  bool shouldRepaint(_GuidePainter old) => old.color != color;
}
