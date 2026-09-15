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
import 'state.dart';

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
    ProfileScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    final unread = context.watch<AppState>().unreadNotifications;
    final wide = MediaQuery.sizeOf(context).width >= 800;
    final destinations = [
      const NavigationDestination(icon: Icon(Icons.center_focus_weak), label: 'Escanear'),
      const NavigationDestination(icon: Icon(Icons.menu_book), label: 'Catálogo'),
      const NavigationDestination(icon: Icon(Icons.collections_bookmark), label: 'Colección'),
      const NavigationDestination(icon: Icon(Icons.storefront), label: 'Mercado'),
      const NavigationDestination(icon: Icon(Icons.newspaper), label: 'Noticias'),
      NavigationDestination(
        icon: Badge(isLabelVisible: unread > 0, label: Text('$unread'), child: const Icon(Icons.person)),
        label: 'Perfil',
      ),
    ];
    final body = KeyedSubtree(key: _bodyKey, child: IndexedStack(index: _index, children: _screens));
    if (wide) {
      return Scaffold(
        floatingActionButton: const AskButton(),
        body: Row(children: [
          NavigationRail(
            selectedIndex: _index,
            onDestinationSelected: (i) => setState(() => _index = i),
            labelType: NavigationRailLabelType.all,
            destinations: [
              for (final d in destinations) NavigationRailDestination(icon: d.icon, label: Text(d.label)),
            ],
          ),
          const VerticalDivider(width: 1),
          Expanded(child: body),
        ]),
      );
    }
    return Scaffold(
      body: body,
      floatingActionButton: const AskButton(),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: destinations,
      ),
    );
  }
}
