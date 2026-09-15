import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'api.dart';
import 'screens/catalog.dart';
import 'screens/chat.dart';
import 'screens/collection.dart';
import 'screens/market.dart';
import 'screens/news.dart';
import 'screens/profile.dart';
import 'screens/scan.dart';
import 'screens/settings.dart';
import 'state.dart';
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
        theme: ThemeData(colorSchemeSeed: const Color(0xFF9C7A2E), useMaterial3: true),
        darkTheme: ThemeData(
            colorSchemeSeed: const Color(0xFFD4AF37), brightness: Brightness.dark, useMaterial3: true),
        home: const _Shell(),
      );
}

class _Shell extends StatefulWidget {
  const _Shell();

  @override
  State<_Shell> createState() => _ShellState();
}

class _ShellState extends State<_Shell> {
  int _index = 0;
  // Keeps tab state alive when the layout flips between rail and bottom bar.
  final _bodyKey = GlobalKey();

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
    final wide = MediaQuery.sizeOf(context).width >= 800;
    final destinations = [
      const NavigationDestination(icon: Icon(Icons.center_focus_weak), label: 'Escanear'),
      const NavigationDestination(icon: Icon(Icons.menu_book), label: 'Catálogo'),
      const NavigationDestination(icon: Icon(Icons.collections_bookmark), label: 'Colección'),
      const NavigationDestination(icon: Icon(Icons.storefront), label: 'Mercado'),
      const NavigationDestination(icon: Icon(Icons.newspaper), label: 'Noticias'),
      const NavigationDestination(icon: Icon(Icons.settings), label: 'Ajustes'),
      NavigationDestination(
        icon: Badge(isLabelVisible: unread > 0, label: Text('$unread'), child: const Icon(Icons.person)),
        label: 'Perfil',
      ),
    ];
    final body = KeyedSubtree(key: _bodyKey, child: LazyIndexedStack(index: _index, children: _screens));
    // Back (browser gesture, Android button) returns to Escanear before leaving the app.
    return PopScope(
      canPop: _index == 0,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _select(0);
      },
      child: wide
          ? Scaffold(
              floatingActionButton: const AskButton(),
              body: Row(children: [
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
              ]),
            )
          : Scaffold(
              body: body,
              floatingActionButton: const AskButton(),
              bottomNavigationBar: NavigationBar(
                selectedIndex: _index,
                onDestinationSelected: _select,
                destinations: destinations,
              ),
            ),
    );
  }
}
