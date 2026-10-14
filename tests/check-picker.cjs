// Verify registry-driven categories while retaining native selection and effort props.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const providers = JSON.parse(fs.readFileSync(path.join(root, 'config/providers.json'), 'utf8'));
const config = {
  providers: [{id: 'openai', label: 'ChatGPT'}, ...Object.entries(providers).map(([id, entry]) => ({id, label: entry.label, defaultModel: entry.default_model}))],
  models: Object.fromEntries(Object.entries(providers).flatMap(([id, entry]) => Object.keys(entry.models).map(model => [model, id]))),
};
const selection = path.join(root, '.local/deployment-path.txt');
const deployment = fs.existsSync(selection) ? fs.readFileSync(selection, 'utf8').trim() : '.local/deployment';
const built = fs.readFileSync(path.join(root, deployment, 'Provider-Overlay.source.js'), 'utf8');
const embedded = JSON.parse(built.split('const gatewayProviderConfig = ')[1].split(/;\r?\n/)[0]);
assert.deepEqual(embedded, config);
config.providers.push({id: 'fixture', label: 'Fixture Provider', defaultModel: 'fixture-model'});
config.models['fixture-model'] = 'fixture';
const reference = {current: {}};
const context = {
  Z: () => ({useState: value => [value, () => {}], useRef: () => reference, useEffect: () => {}}),
  CU: {Fragment: 'fragment', jsx: (type, props) => ({type, ...props}), jsxs: (type, props) => ({type, ...props})},
  mh: {Title: 'title', Item: 'item', Separator: 'separator'}, wn: 'selected-icon',
};
vm.createContext(context);
vm.runInContext('const gatewayProviderConfig = ' + JSON.stringify(config) + ';\n' + fs.readFileSync(path.join(root, 'src/ui/provider-picker.js'), 'utf8'), context);
(async () => {
  const selected = [];
  const options = ['gpt-native-fixture', ...Object.keys(config.models)].map(id => ({id: id + ':high', onSelect: () => {selected.push(id);}}));
  for (const provider of config.providers) {
    const model = provider.id === 'openai' ? 'gpt-native-fixture' : provider.defaultModel;
    const props = {active: true, selectedPowerSelection: {model, reasoningEffort: 'high'}, modelListConfig: {options, defaultOption: 'native-default', extras: 'native-extra'}, onToggleMenuView: view => assert.equal(view, 'simple')};
    const result = context.gatewayPickerMenuProps(props);
    assert.strictEqual(result.selectedPowerSelection, props.selectedPowerSelection);
    assert.equal(result.modelListConfig.defaultOption, provider.id === 'openai' ? 'native-default' : null);
    assert(result.modelListConfig.options.every(option => context.gatewayPickerOptionProvider(option) === provider.id));
    assert(result.modelListConfig.options.length > 0);
    const next = config.providers.find(entry => entry.id !== provider.id && entry.id !== 'openai');
    const item = result.menuHeader.children.find(child => child?.children === next.label);
    item.onSelect({preventDefault() {}});
    await Promise.resolve();
    assert.equal(selected.at(-1), next.defaultModel);
  }
  console.log('PASS: generated registry matches configuration; provider filters/defaults, new category, original callbacks and effort props preserved.');
})().catch(error => {console.error(error); process.exitCode = 1;});
