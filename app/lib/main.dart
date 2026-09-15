import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'api.dart';
import 'onboarding/coach_marks.dart';
import 'screens/catalog.dart';
import 'screens/chat.dart';
import 'screens/collection.dart';
import 'screens/market.dart';
import 'screens/news.dart';
import 'screens/profile.dart';
import 'screens/scan.dart';
import 'screens/settings.dart';
import 'state.dart';
import 'theme.dart';
import 'widgets/lazy_indexed_stack.dart';

/// When euro2-core serves the web build itself at /app, the API is on the same origin.
String _defaultBaseUrl() {
  if (kIsWeb && Uri.base.path.startsWith('/app')) return Uri.base.origin;
  return 'http://localhost:8000';
}

void main() {
  final state = AppState(Euro2Api(baseUrl: _defaultBaseUrl()));
  runApp(ChangeNotifierProvider.value(value: state, child: const Euro2App()));
  state.restore();
}

class Euro2App extends StatelessWidget {
  const Euro2App({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Euro2 - monedas de 2 EUR',
    debugShowCheckedModeBanner: false,
    // select, not watch: the whole app must not rebuild on every AppState change
    themeMode: context.select((AppState s) => s.themeMode),
    theme: AppTheme.light(),
    darkTheme: AppTheme.dark(),
    home: const _Shell(),
  );
}

class _Shell extends StatefulWidget {
  const _Shell();

  @override
  State<_Shell> createState() => _ShellState();
}

/// Lets any screen switch tabs or replay the tour (Ajustes -> "Ver el tutorial").
class ShellScope extends InheritedWidget {
  const ShellScope({super.key, required this.selectTab, required this.showTutorial, required super.child});
  final void Function(int index) selectTab;
  final Future<void> Function() showTutorial;

  static ShellScope? of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<ShellScope>();

  @override
  bool updateShouldNotify(ShellScope old) => false;
}

class _ShellState extends State<_Shell> {
  int _index = 0;
  // Keeps tab state alive when the layout flips between rail and bottom bar.
  final _bodyKey = GlobalKey();
  // Tour targets: one key per destination (only one bar exists at a time) plus the FAB.
  final _navKeys = List.generate(7, (_) => GlobalKey());
  final _fabKey = GlobalKey();
  bool _tourScheduled = false;

  Future<void> _showTutorial() async {
    _select(0);
    await Future<void>.delayed(const Duration(milliseconds: 350)); // let the layout settle
    if (!mounted) return;
    await CoachMarks.show(context, [
      CoachStep(
        target: _navKeys[0],
        title: 'Escanear',
        body:
            'Haz una foto a la cara nacional de una moneda de 2 € y te decimos cuál es, '
            'qué tirada tiene y cuánto vale de verdad.',
      ),
      CoachStep(
        target: _navKeys[1],
        title: 'Catálogo',
        body:
            'Todas las monedas de 2 € del mundo con su valor. Filtra por país, año, '
            'categoría o precio.',
      ),
      CoachStep(
        target: _navKeys[3],
        title: 'Mercado',
        body: 'Chollos detectados, consejos para comprar y vender, y las monedas que sigues.',
      ),
      CoachStep(
        target: _fabKey,
        title: 'Pregunta',
        body:
            'Un asistente local que responde dudas de numismática y de tus monedas, '
            'sin depender de servicios externos.',
      ),
      CoachStep(
        target: _navKeys[5],
        title: 'Ajustes',
        body: 'Idioma, tema, instalar la app en el móvil y volver a ver este tutorial.',
      ),
    ]);
    if (mounted) await context.read<AppState>().markOnboardingDone();
  }

  static const _screens = [
    ScanScreen(),
    CatalogScreen(),
    CollectionScreen(),
    MarketScreen(),
    NewsScreen(),
    SettingsScreen(),
    ProfileScreen(),
  ];

  void _select(int i) {
    if (i != _index) setState(() => _index = i);
  }

  @override
  Widget build(BuildContext context) {
    final unread = context.select((AppState s) => s.unreadNotifications);
    final firstRun = context.select((AppState s) => s.restored && !s.onboardingDone);
    if (firstRun && !_tourScheduled) {
      _tourScheduled = true;
      WidgetsBinding.instance.addPostFrameCallback((_) => _showTutorial());
    }
    final wide = MediaQuery.sizeOf(context).width >= 800;
    const icons = [
      Icons.center_focus_weak,
      Icons.menu_book,
      Icons.collections_bookmark,
      Icons.storefront,
      Icons.newspaper,
      Icons.settings,
      Icons.person,
    ];
    const labels = ['Escanear', 'Catálogo', 'Colección', 'Mercado', 'Noticias', 'Ajustes', 'Perfil'];
    final destinations = [
      for (var i = 0; i < labels.length; i++)
        NavigationDestination(
          icon: KeyedSubtree(
            key: _navKeys[i],
            child: i == 6
                ? Badge(isLabelVisible: unread > 0, label: Text('$unread'), child: Icon(icons[i]))
                : Icon(icons[i]),
          ),
          label: labels[i],
        ),
    ];
    final body = KeyedSubtree(
      key: _bodyKey,
      child: LazyIndexedStack(index: _index, children: _screens),
    );
    // Back (browser gesture, Android button) returns to Escanear before leaving the app.
    return ShellScope(
      selectTab: _select,
      showTutorial: _showTutorial,
      child: PopScope(
        canPop: _index == 0,
        onPopInvokedWithResult: (didPop, _) {
          if (!didPop) _select(0);
        },
        child: wide
            ? Scaffold(
                floatingActionButton: AskButton(key: _fabKey),
                body: Row(
                  children: [
                    NavigationRail(
                      selectedIndex: _index,
                      onDestinationSelected: _select,
                      labelType: NavigationRailLabelType.all,
                      destinations: [
                        for (final d in destinations)
                          NavigationRailDestination(icon: d.icon, label: Text(d.label)),
                      ],
                    ),
                    const VerticalDivider(width: 1),
                    Expanded(child: body),
                  ],
                ),
              )
            : Scaffold(
                body: body,
                floatingActionButton: AskButton(key: _fabKey),
                bottomNavigationBar: NavigationBar(
                  selectedIndex: _index,
                  onDestinationSelected: _select,
                  // seven tabs: on narrow phones only the active label fits
                  labelBehavior: MediaQuery.sizeOf(context).width < 430
                      ? NavigationDestinationLabelBehavior.onlyShowSelected
                      : NavigationDestinationLabelBehavior.alwaysShow,
                  destinations: destinations,
                ),
              ),
      ),
    );
  }
}
