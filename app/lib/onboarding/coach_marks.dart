import 'dart:async';

import 'package:flutter/material.dart';

/// One stop of the guided tour: a widget to spotlight and what to say about it.
class CoachStep {
  const CoachStep({required this.target, required this.title, required this.body});
  final GlobalKey target;
  final String title;
  final String body;
}

/// Spotlight bubbles over the real interface (no separate carousel to keep in sync).
/// Steps whose target is not on screen are skipped, so the same tour works with the
/// bottom bar on phones and the side rail on wide screens.
class CoachMarks {
  static Future<void> show(BuildContext context, List<CoachStep> steps) {
    final overlay = Overlay.of(context, rootOverlay: true);
    final done = Completer<void>();
    late OverlayEntry entry;
    entry = OverlayEntry(
      builder: (_) => _CoachOverlay(
        steps: steps,
        onDone: () {
          entry.remove();
          done.complete();
        },
      ),
    );
    overlay.insert(entry);
    return done.future;
  }
}

class _CoachOverlay extends StatefulWidget {
  const _CoachOverlay({required this.steps, required this.onDone});
  final List<CoachStep> steps;
  final VoidCallback onDone;

  @override
  State<_CoachOverlay> createState() => _CoachOverlayState();
}

class _CoachOverlayState extends State<_CoachOverlay> with WidgetsBindingObserver {
  int _index = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _skipMissing();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  // The layout can flip between rail and bar while the tour is open: re-measure.
  @override
  void didChangeMetrics() => setState(() {});

  Rect? _targetRect(CoachStep step) {
    final box = step.target.currentContext?.findRenderObject();
    if (box is! RenderBox || !box.hasSize || !box.attached) return null;
    return (box.localToGlobal(Offset.zero) & box.size).inflate(8);
  }

  void _skipMissing() {
    while (_index < widget.steps.length && _targetRect(widget.steps[_index]) == null) {
      _index++;
    }
    if (_index >= widget.steps.length) widget.onDone();
  }

  void _next() {
    _index++;
    _skipMissing();
    if (mounted && _index < widget.steps.length) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    if (_index >= widget.steps.length) return const SizedBox.shrink();
    final step = widget.steps[_index];
    final rect = _targetRect(step);
    if (rect == null) return const SizedBox.shrink();
    final screen = MediaQuery.sizeOf(context);
    final scheme = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    final last = _index == widget.steps.length - 1;

    final width = (screen.width - 32).clamp(200.0, 340.0);
    final left = (rect.center.dx - width / 2).clamp(16.0, screen.width - width - 16);
    final above = rect.center.dy > screen.height / 2;

    final bubble = Material(
      color: scheme.surfaceContainerHigh,
      elevation: 8,
      borderRadius: BorderRadius.circular(16),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(18, 16, 18, 10),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(step.title, style: text.titleMedium?.copyWith(color: scheme.primary)),
            const SizedBox(height: 6),
            Text(step.body, style: text.bodyMedium),
            const SizedBox(height: 8),
            Row(
              children: [
                Text('${_index + 1} / ${widget.steps.length}', style: text.labelSmall),
                const Spacer(),
                if (!last) TextButton(onPressed: widget.onDone, child: const Text('Saltar')),
                FilledButton(
                  onPressed: last ? widget.onDone : _next,
                  child: Text(last ? 'Entendido' : 'Siguiente'),
                ),
              ],
            ),
          ],
        ),
      ),
    );

    return Stack(
      fit: StackFit.expand,
      children: [
        // dark veil with a hole over the target; a tap anywhere advances
        GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: last ? widget.onDone : _next,
          child: CustomPaint(painter: _SpotlightPainter(rect, scheme.primary)),
        ),
        AnimatedPositioned(
          duration: const Duration(milliseconds: 220),
          curve: Curves.easeOut,
          left: left,
          width: width,
          top: above ? null : rect.bottom + 12,
          bottom: above ? screen.height - rect.top + 12 : null,
          child: bubble,
        ),
      ],
    );
  }
}

class _SpotlightPainter extends CustomPainter {
  _SpotlightPainter(this.hole, this.accent);
  final Rect hole;
  final Color accent;

  @override
  void paint(Canvas canvas, Size size) {
    final rrect = RRect.fromRectAndRadius(hole, const Radius.circular(14));
    final veil = Path.combine(
      PathOperation.difference,
      Path()..addRect(Offset.zero & size),
      Path()..addRRect(rrect),
    );
    canvas.drawPath(veil, Paint()..color = Colors.black.withValues(alpha: 0.7));
    canvas.drawRRect(
      rrect,
      Paint()
        ..color = accent
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
  }

  @override
  bool shouldRepaint(_SpotlightPainter old) => old.hole != hole || old.accent != accent;
}
