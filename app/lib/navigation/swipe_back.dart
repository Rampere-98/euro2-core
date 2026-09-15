import 'package:flutter/cupertino.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

/// A page route that can be dismissed by dragging it to the right from anywhere on the page.
///
/// Flutter's own iOS back gesture only listens to the leftmost 20 px, which Safari reserves for
/// its history swipe, so on an iPhone in the browser it never fires. This route keeps the
/// Cupertino slide transition on every platform and drives it from a full-page horizontal drag.
/// Children still win the gesture arena: tab views, zoomable photos and charts keep working.
class SwipeBackRoute<T> extends MaterialPageRoute<T> {
  SwipeBackRoute({required super.builder, super.settings, super.fullscreenDialog});

  @override
  Duration get transitionDuration => const Duration(milliseconds: 320);

  @override
  Widget buildTransitions(BuildContext context, Animation<double> animation,
      Animation<double> secondaryAnimation, Widget child) {
    return CupertinoPageTransition(
      primaryRouteAnimation: animation,
      secondaryRouteAnimation: secondaryAnimation,
      linearTransition: navigator!.userGestureInProgress,
      child: _SwipeBackDetector(route: this, child: child),
    );
  }

  bool get _gestureEnabled =>
      !isFirst &&
      !fullscreenDialog &&
      animation!.isCompleted &&
      popDisposition == RoutePopDisposition.pop &&
      !navigator!.userGestureInProgress;

  AnimationController get _controller => controller!;
}

class _SwipeBackDetector extends StatefulWidget {
  const _SwipeBackDetector({required this.route, required this.child});
  final SwipeBackRoute<dynamic> route;
  final Widget child;

  @override
  State<_SwipeBackDetector> createState() => _SwipeBackDetectorState();
}

class _SwipeBackDetectorState extends State<_SwipeBackDetector> {
  _BackGesture? _gesture;

  void _onStart(DragStartDetails d) {
    if (!widget.route._gestureEnabled) return;
    _gesture = _BackGesture(widget.route);
  }

  void _onUpdate(DragUpdateDetails d) {
    _gesture?.dragUpdate(d.primaryDelta! / context.size!.width);
  }

  void _onEnd(DragEndDetails d) {
    _gesture?.dragEnd(d.velocity.pixelsPerSecond.dx / context.size!.width);
    _gesture = null;
  }

  void _onCancel() {
    _gesture?.dragEnd(0);
    _gesture = null;
  }

  @override
  Widget build(BuildContext context) => RawGestureDetector(
        behavior: HitTestBehavior.translucent,
        gestures: {
          HorizontalDragGestureRecognizer:
              GestureRecognizerFactoryWithHandlers<HorizontalDragGestureRecognizer>(
            () => HorizontalDragGestureRecognizer(debugOwner: this),
            (r) => r
              ..onStart = _onStart
              ..onUpdate = _onUpdate
              ..onEnd = _onEnd
              ..onCancel = _onCancel,
          ),
        },
        child: widget.child,
      );
}

/// Drives the route's animation from a drag: 1.0 = in place, 0.0 = fully dismissed.
class _BackGesture {
  _BackGesture(this.route) {
    route.navigator!.didStartUserGesture();
  }

  final SwipeBackRoute<dynamic> route;
  AnimationController get _c => route._controller;
  NavigatorState get _navigator => route.navigator!;

  void dragUpdate(double delta) => _c.value = (_c.value - delta).clamp(0.0, 1.0);

  void dragEnd(double velocity) {
    // Flicked right fast enough, or dragged past the middle: dismiss.
    final dismiss = velocity > 1.0 || (velocity > -1.0 && _c.value < 0.5);
    if (dismiss) {
      _navigator.pop();
      if (_c.isAnimating) {
        final ms = (300 * _c.value).round().clamp(80, 300);
        _c.animateBack(0.0, duration: Duration(milliseconds: ms), curve: Curves.easeOut);
      }
    } else {
      final ms = (300 * (1 - _c.value)).round().clamp(80, 300);
      _c.animateTo(1.0, duration: Duration(milliseconds: ms), curve: Curves.easeOut);
    }
    if (_c.isAnimating) {
      late final AnimationStatusListener done;
      done = (_) {
        _navigator.didStopUserGesture();
        _c.removeStatusListener(done);
      };
      _c.addStatusListener(done);
    } else {
      _navigator.didStopUserGesture();
    }
  }
}
