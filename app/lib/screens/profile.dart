import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state.dart';
import '../widgets.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _name = TextEditingController();
  String? _country;
  bool _register = false;
  bool _busy = false;

  Future<void> _submit() async {
    final state = context.read<AppState>();
    setState(() => _busy = true);
    try {
      if (_register) {
        await state.register(_email.text.trim(), _password.text, _name.text.trim(), _country);
      } else {
        await state.login(_email.text.trim(), _password.text);
      }
      _password.clear();
    } catch (e) {
      if (mounted) showError(context, e);
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _showNotifications() async {
    final state = context.read<AppState>();
    try {
      final list = List<Map<String, dynamic>>.from(await state.api.get('/me/notifications'));
      if (!mounted) return;
      await showModalBottomSheet(
        context: context,
        showDragHandle: true,
        builder: (_) => ListView(padding: const EdgeInsets.all(16), children: [
          Text('Notificaciones', style: Theme.of(context).textTheme.titleMedium),
          if (list.isEmpty) const Text('Nada nuevo.'),
          for (final n in list)
            ListTile(
              dense: true,
              leading: Icon(n['read_at'] == null ? Icons.circle_notifications : Icons.notifications_none),
              title: Text(n['title']),
              subtitle: n['body'] != null ? Text(n['body']) : null,
            ),
        ]),
      );
      await state.api.post('/me/notifications/read');
      await state.refreshNotifications();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _showLeaderboard() async {
    final api = context.read<AppState>().api;
    try {
      final rows = List<Map<String, dynamic>>.from(await api.get('/leaderboard'));
      if (!mounted) return;
      await showModalBottomSheet(
        context: context,
        showDragHandle: true,
        builder: (_) => ListView(padding: const EdgeInsets.all(16), children: [
          Text('Clasificación', style: Theme.of(context).textTheme.titleMedium),
          for (var i = 0; i < rows.length; i++)
            ListTile(
              dense: true,
              leading: CircleAvatar(child: Text('${i + 1}')),
              title: Text(rows[i]['display_name'] ?? ''),
              subtitle: Text('${rows[i]['pieces']} piezas · ${rows[i]['score']} puntos'
                  '${rows[i]['country_code'] != null ? ' · ${countryName(rows[i]['country_code'])}' : ''}'),
            ),
        ]),
      );
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _editServer() async {
    final state = context.read<AppState>();
    final ctrl = TextEditingController(text: state.api.baseUrl);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Servidor euro2-core'),
        content: TextField(controller: ctrl, decoration: const InputDecoration(hintText: 'http://localhost:8000')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Guardar')),
        ],
      ),
    );
    if (ok == true) await state.setBaseUrl(ctrl.text);
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final user = state.user;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Perfil'),
        actions: [
          if (state.loggedIn)
            IconButton(
              tooltip: 'Notificaciones',
              onPressed: _showNotifications,
              icon: Badge(
                isLabelVisible: state.unreadNotifications > 0,
                label: Text('${state.unreadNotifications}'),
                child: const Icon(Icons.notifications),
              ),
            ),
          IconButton(tooltip: 'Servidor', onPressed: _editServer, icon: const Icon(Icons.dns)),
        ],
      ),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        if (user == null) ...[
          SegmentedButton<bool>(
            segments: const [
              ButtonSegment(value: false, label: Text('Entrar')),
              ButtonSegment(value: true, label: Text('Crear cuenta')),
            ],
            selected: {_register},
            onSelectionChanged: (s) => setState(() => _register = s.first),
          ),
          const SizedBox(height: 12),
          TextField(
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              autofillHints: const [AutofillHints.email],
              decoration: const InputDecoration(labelText: 'Email', border: OutlineInputBorder())),
          const SizedBox(height: 8),
          TextField(
              controller: _password,
              obscureText: true,
              onSubmitted: (_) => _submit(),
              decoration: const InputDecoration(labelText: 'Contraseña (mín. 8)', border: OutlineInputBorder())),
          if (_register) ...[
            const SizedBox(height: 8),
            TextField(
                controller: _name,
                decoration: const InputDecoration(labelText: 'Nombre visible', border: OutlineInputBorder())),
            const SizedBox(height: 8),
            DropdownButtonFormField<String?>(
              initialValue: _country,
              decoration: const InputDecoration(labelText: 'País (opcional)', border: OutlineInputBorder()),
              items: [
                const DropdownMenuItem(value: null, child: Text('—')),
                for (final e in kCountryNames.entries) DropdownMenuItem(value: e.key, child: Text(e.value)),
              ],
              onChanged: (v) => setState(() => _country = v),
            ),
          ],
          const SizedBox(height: 12),
          FilledButton(
              onPressed: _busy ? null : _submit, child: Text(_register ? 'Crear cuenta' : 'Entrar')),
          const SizedBox(height: 24),
          const Text('Sin cuenta puedes identificar monedas y consultar el catálogo. '
              'Con cuenta gratuita: colección, valor, logros y mercado (hasta 3 anuncios).'),
        ] else ...[
          ListTile(
            leading: CircleAvatar(child: Text((user['display_name'] as String).substring(0, 1).toUpperCase())),
            title: Text(user['display_name']),
            subtitle: Text('${user['email']}'
                '${user['country_code'] != null ? ' · ${countryName(user['country_code'])}' : ''}'),
          ),
          Wrap(children: [
            Chip2(state.isPro ? 'Plan Pro' : 'Plan gratuito', color: state.isPro ? Colors.amber : null),
            if (user['role'] == 'expert') const Chip2('experto', color: Colors.blue),
            if (user['role'] == 'admin') const Chip2('admin', color: Colors.red),
          ]),
          const SizedBox(height: 12),
          if (!state.isPro)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Pasa a Pro', style: Theme.of(context).textTheme.titleMedium),
                  const Text('Alertas de precio, anuncios ilimitados en el mercado y estadísticas avanzadas.'),
                  const SizedBox(height: 8),
                  FilledButton.tonal(
                    onPressed: () async {
                      try {
                        await state.upgradeToPro();
                      } catch (e) {
                        if (context.mounted) showError(context, e);
                      }
                    },
                    child: const Text('Activar Pro (demo, sin pago)'),
                  ),
                ]),
              ),
            ),
          ListTile(
              leading: const Icon(Icons.leaderboard),
              title: const Text('Clasificación de coleccionistas'),
              onTap: _showLeaderboard),
          if (state.isPro) const _AlertsTile(),
          ListTile(
              leading: const Icon(Icons.logout), title: const Text('Cerrar sesión'), onTap: state.logout),
        ],
        const SizedBox(height: 24),
        Text('Servidor: ${state.api.baseUrl}', style: Theme.of(context).textTheme.labelSmall),
      ]),
    );
  }
}

class _AlertsTile extends StatelessWidget {
  const _AlertsTile();

  @override
  Widget build(BuildContext context) {
    final api = context.read<AppState>().api;
    return ListTile(
      leading: const Icon(Icons.notifications_active),
      title: const Text('Mis alertas de precio'),
      onTap: () async {
        try {
          final alerts = List<Map<String, dynamic>>.from(await api.get('/me/alerts'));
          if (!context.mounted) return;
          await showModalBottomSheet(
            context: context,
            showDragHandle: true,
            builder: (_) => ListView(padding: const EdgeInsets.all(16), children: [
              Text('Alertas activas (${alerts.length})', style: Theme.of(context).textTheme.titleMedium),
              if (alerts.isEmpty)
                const Text('Crea alertas desde la ficha de una variante (próximamente en la app; ya disponible vía API).'),
              for (final a in alerts)
                ListTile(
                  dense: true,
                  title: Text('${a['direction'] == 'above' ? 'Sube de' : 'Baja de'} ${euro(a['threshold'])}'),
                  subtitle: Text('variante ${a['issue_id']}'),
                  trailing: IconButton(
                      icon: const Icon(Icons.delete),
                      onPressed: () async {
                        await api.delete('/me/alerts/${a['id']}');
                        if (context.mounted) Navigator.pop(context);
                      }),
                ),
            ]),
          );
        } catch (e) {
          if (context.mounted) showError(context, e);
        }
      },
    );
  }
}
