import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme.dart';

/// Small national flag from the bundled PNGs (no emoji: CanvasKit would download a
/// multi-megabyte emoji font and Windows has no flag glyphs at all).
class CountryFlag extends StatelessWidget {
  const CountryFlag(this.code, {super.key, this.height = 14});
  final String? code;
  final double height;

  @override
  Widget build(BuildContext context) {
    final cc = code?.toLowerCase();
    if (cc == null) return const SizedBox.shrink();
    return ClipRRect(
      borderRadius: BorderRadius.circular(2),
      child: Image.asset(
        'assets/flags/$cc.png',
        height: height,
        fit: BoxFit.contain,
        filterQuality: FilterQuality.medium,
        errorBuilder: (_, _, _) => const SizedBox.shrink(),
      ),
    );
  }
}

/// A coin (or a placeholder) inside a brushed gold ring: the visual signature of the app.
/// The ring is a single sweep gradient stroke, cheap to paint and static unless [spin].
class GoldRing extends StatefulWidget {
  const GoldRing({super.key, required this.child, required this.size, this.spin = false, this.width = 3});
  final Widget child;
  final double size;
  final bool spin;
  final double width;

  @override
  State<GoldRing> createState() => _GoldRingState();
}

class _GoldRingState extends State<GoldRing> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(seconds: 9));

  @override
  void initState() {
    super.initState();
    if (widget.spin) _c.repeat();
  }

  @override
  void didUpdateWidget(GoldRing old) {
    super.didUpdateWidget(old);
    if (widget.spin && !_c.isAnimating) _c.repeat();
    if (!widget.spin && _c.isAnimating) _c.stop();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => RepaintBoundary(
        child: SizedBox(
          width: widget.size,
          height: widget.size,
          child: AnimatedBuilder(
            animation: _c,
            builder: (_, child) => CustomPaint(
              painter: _RingPainter(turn: _c.value, width: widget.width),
              child: child,
            ),
            child: Padding(padding: EdgeInsets.all(widget.width + 4), child: ClipOval(child: widget.child)),
          ),
        ),
      );
}

class _RingPainter extends CustomPainter {
  _RingPainter({required this.turn, required this.width});
  final double turn;
  final double width;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = width
      ..shader = SweepGradient(
        transform: GradientRotation(turn * 2 * math.pi),
        colors: const [AppTheme.brass, AppTheme.gold, Color(0xFFF6E3A1), AppTheme.gold, AppTheme.brass],
        stops: const [0, .3, .5, .7, 1],
      ).createShader(rect);
    canvas.drawCircle(rect.center, size.shortestSide / 2 - width / 2, paint);
  }

  @override
  bool shouldRepaint(_RingPainter old) => old.turn != turn || old.width != width;
}

/// Section heading in the display face with a short gold rule, used by every screen.
class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing});
  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: Space.lg, bottom: Space.sm),
        child: Row(children: [
          Container(width: 3, height: 18, decoration: BoxDecoration(color: AppTheme.gold, borderRadius: BorderRadius.circular(2))),
          const SizedBox(width: Space.sm),
          Expanded(child: Text(text, style: Theme.of(context).textTheme.titleLarge)),
          ?trailing,
        ]),
      );
}
