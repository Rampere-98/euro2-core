import 'package:flutter/material.dart';

/// Euro2's look: a warm dark ground with brass and gold as the accent, serif display type for
/// titles and a clean sans for data. The dark theme is the flagship; the light one keeps the
/// same materials on parchment. Everything is plain Material 3 with explicit tokens: no
/// shaders, no blur, so it stays smooth on phones in the browser.
class AppTheme {
  static const gold = Color(0xFFD4AF37);
  static const brass = Color(0xFFB08D57);
  static const ink = Color(0xFF14110D);
  static const olive = Color(0xFF8FA36B);
  static const claret = Color(0xFFE5484D);

  static const display = 'PlayfairDisplay';
  static const sans = 'Inter';

  static ThemeData dark() => _build(const ColorScheme(
        brightness: Brightness.dark,
        primary: gold,
        onPrimary: Color(0xFF1C1600),
        primaryContainer: Color(0xFF4A3A0C),
        onPrimaryContainer: Color(0xFFF6E3A1),
        secondary: brass,
        onSecondary: Color(0xFF1C1600),
        secondaryContainer: Color(0xFF3B2F1E),
        onSecondaryContainer: Color(0xFFEBD9BE),
        tertiary: olive,
        onTertiary: Color(0xFF101A05),
        tertiaryContainer: Color(0xFF2E3A1C),
        onTertiaryContainer: Color(0xFFD5E4BA),
        error: claret,
        onError: Colors.white,
        errorContainer: Color(0xFF5C1A1D),
        onErrorContainer: Color(0xFFFFD9DA),
        surface: ink,
        onSurface: Color(0xFFEFE8DA),
        onSurfaceVariant: Color(0xFFB8AE9C),
        surfaceContainerLowest: Color(0xFF0E0C09),
        surfaceContainerLow: Color(0xFF1A1610),
        surfaceContainer: Color(0xFF1F1A14),
        surfaceContainerHigh: Color(0xFF29231B),
        surfaceContainerHighest: Color(0xFF342D23),
        outline: Color(0xFF6E6555),
        outlineVariant: Color(0xFF3D362B),
        inverseSurface: Color(0xFFEFE8DA),
        onInverseSurface: ink,
        inversePrimary: Color(0xFF7A5F12),
        shadow: Colors.black,
        scrim: Colors.black,
      ));

  static ThemeData light() => _build(const ColorScheme(
        brightness: Brightness.light,
        primary: Color(0xFF8A6A1C),
        onPrimary: Colors.white,
        primaryContainer: Color(0xFFF6E3A1),
        onPrimaryContainer: Color(0xFF2B1F00),
        secondary: Color(0xFF7A5C33),
        onSecondary: Colors.white,
        secondaryContainer: Color(0xFFEBD9BE),
        onSecondaryContainer: Color(0xFF2A1D0A),
        tertiary: Color(0xFF5C6E3A),
        onTertiary: Colors.white,
        tertiaryContainer: Color(0xFFD5E4BA),
        onTertiaryContainer: Color(0xFF1A2508),
        error: Color(0xFFB3261E),
        onError: Colors.white,
        errorContainer: Color(0xFFF9DEDC),
        onErrorContainer: Color(0xFF410E0B),
        surface: Color(0xFFFBF7EE),
        onSurface: Color(0xFF221D15),
        onSurfaceVariant: Color(0xFF5E5647),
        surfaceContainerLowest: Colors.white,
        surfaceContainerLow: Color(0xFFF5EFE2),
        surfaceContainer: Color(0xFFEFE8D8),
        surfaceContainerHigh: Color(0xFFE8E0CE),
        surfaceContainerHighest: Color(0xFFE1D8C4),
        outline: Color(0xFF8C8271),
        outlineVariant: Color(0xFFD5CBB6),
        inverseSurface: Color(0xFF332E25),
        onInverseSurface: Color(0xFFF5EFE2),
        inversePrimary: gold,
        shadow: Colors.black,
        scrim: Colors.black,
      ));

  static ThemeData _build(ColorScheme scheme) {
    final dark = scheme.brightness == Brightness.dark;
    final base = ThemeData(colorScheme: scheme, useMaterial3: true, fontFamily: sans);
    final serif = TextStyle(fontFamily: display, color: scheme.onSurface, height: 1.15);
    final sansStyle = TextStyle(fontFamily: sans, color: scheme.onSurface);
    final text = base.textTheme.copyWith(
      displayLarge: serif.copyWith(fontSize: 48, fontWeight: FontWeight.w600),
      displayMedium: serif.copyWith(fontSize: 38, fontWeight: FontWeight.w600),
      displaySmall: serif.copyWith(fontSize: 30, fontWeight: FontWeight.w600),
      headlineLarge: serif.copyWith(fontSize: 28, fontWeight: FontWeight.w600),
      headlineMedium: serif.copyWith(fontSize: 24, fontWeight: FontWeight.w600),
      headlineSmall: serif.copyWith(fontSize: 21, fontWeight: FontWeight.w600),
      titleLarge: serif.copyWith(fontSize: 20, fontWeight: FontWeight.w600),
      titleMedium: sansStyle.copyWith(fontSize: 16, fontWeight: FontWeight.w600, height: 1.3),
      titleSmall: sansStyle.copyWith(fontSize: 14, fontWeight: FontWeight.w600, height: 1.3),
      labelLarge: sansStyle.copyWith(fontSize: 14, fontWeight: FontWeight.w600, letterSpacing: .2),
      labelMedium: sansStyle.copyWith(fontSize: 12, fontWeight: FontWeight.w500),
      labelSmall: sansStyle.copyWith(fontSize: 11, color: scheme.onSurfaceVariant),
      bodyLarge: sansStyle.copyWith(fontSize: 16, height: 1.45),
      bodyMedium: sansStyle.copyWith(fontSize: 14, height: 1.45),
      bodySmall: TextStyle(fontFamily: sans, fontSize: 12, height: 1.4, color: scheme.onSurfaceVariant),
    );
    final hairline = BorderSide(color: scheme.primary.withValues(alpha: dark ? 0.16 : 0.22));
    final radius16 = BorderRadius.circular(16);
    return base.copyWith(
      textTheme: text,
      scaffoldBackgroundColor: scheme.surface,
      splashFactory: InkSparkle.splashFactory,
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surface,
        surfaceTintColor: Colors.transparent,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: text.titleLarge,
        iconTheme: IconThemeData(color: scheme.onSurface),
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: scheme.surfaceContainer,
        surfaceTintColor: Colors.transparent,
        margin: const EdgeInsets.symmetric(vertical: 6),
        shape: RoundedRectangleBorder(borderRadius: radius16, side: hairline),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: scheme.surfaceContainerLow,
        surfaceTintColor: Colors.transparent,
        indicatorColor: scheme.primary.withValues(alpha: 0.2),
        height: 68,
        labelTextStyle: WidgetStatePropertyAll(text.labelLarge?.copyWith(fontSize: 11)),
        iconTheme: WidgetStateProperty.resolveWith((s) => IconThemeData(
            color: s.contains(WidgetState.selected) ? scheme.primary : scheme.onSurfaceVariant)),
      ),
      navigationRailTheme: NavigationRailThemeData(
        backgroundColor: scheme.surfaceContainerLow,
        indicatorColor: scheme.primary.withValues(alpha: 0.2),
        selectedIconTheme: IconThemeData(color: scheme.primary),
        unselectedIconTheme: IconThemeData(color: scheme.onSurfaceVariant),
        selectedLabelTextStyle: text.labelLarge?.copyWith(fontSize: 11, color: scheme.primary),
        unselectedLabelTextStyle: text.labelLarge?.copyWith(fontSize: 11, color: scheme.onSurfaceVariant),
      ),
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: scheme.primary,
        foregroundColor: scheme.onPrimary,
        elevation: 2,
        shape: const StadiumBorder(),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(0, 48),
          padding: const EdgeInsets.symmetric(horizontal: 20),
          shape: const StadiumBorder(),
          textStyle: text.labelLarge,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(0, 48),
          padding: const EdgeInsets.symmetric(horizontal: 20),
          shape: const StadiumBorder(),
          side: BorderSide(color: scheme.primary.withValues(alpha: 0.5)),
          textStyle: text.labelLarge,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(shape: const StadiumBorder(), textStyle: text.labelLarge),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: scheme.surfaceContainerHigh,
        side: BorderSide(color: scheme.outlineVariant),
        shape: const StadiumBorder(),
        labelStyle: text.labelLarge?.copyWith(fontSize: 12, color: scheme.onSurface),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: scheme.surfaceContainer,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: hairline),
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: hairline),
        focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(14), borderSide: BorderSide(color: scheme.primary, width: 1.5)),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      ),
      segmentedButtonTheme: SegmentedButtonThemeData(
        style: SegmentedButton.styleFrom(
          selectedBackgroundColor: scheme.primary.withValues(alpha: 0.22),
          selectedForegroundColor: scheme.primary,
          side: BorderSide(color: scheme.outlineVariant),
        ),
      ),
      listTileTheme: ListTileThemeData(
        iconColor: scheme.onSurfaceVariant,
        titleTextStyle: text.titleSmall,
        subtitleTextStyle: text.bodySmall,
      ),
      dividerTheme: DividerThemeData(color: scheme.outlineVariant, space: 1),
      dialogTheme: DialogThemeData(
        backgroundColor: scheme.surfaceContainerHigh,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
        titleTextStyle: text.headlineSmall,
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: scheme.surfaceContainerHigh,
        surfaceTintColor: Colors.transparent,
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
        showDragHandle: true,
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: scheme.inverseSurface,
        contentTextStyle: text.bodyMedium?.copyWith(color: scheme.onInverseSurface),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
      tabBarTheme: TabBarThemeData(
        labelColor: scheme.primary,
        unselectedLabelColor: scheme.onSurfaceVariant,
        indicatorColor: scheme.primary,
        dividerColor: scheme.outlineVariant,
        labelStyle: text.labelLarge,
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(color: scheme.primary),
    );
  }
}

/// Spacing scale used across screens.
abstract final class Space {
  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 12.0;
  static const lg = 16.0;
  static const xl = 24.0;
  static const xxl = 32.0;
}
