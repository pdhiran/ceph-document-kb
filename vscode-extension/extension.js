const vscode = require('vscode');
const axios = require('axios');

let statusBarItem;
let outputChannel;

function getConfig() {
    const config = vscode.workspace.getConfiguration('ceph-doc-kb');
    return {
        apiUrl: config.get('apiUrl', 'http://localhost:8100'),
        defaultComponent: config.get('defaultComponent', ''),
    };
}

async function apiCall(endpoint, params = {}) {
    const { apiUrl } = getConfig();
    const response = await axios.get(`${apiUrl}${endpoint}`, { params, timeout: 10000 });
    return response.data;
}

async function updateStatusBar() {
    try {
        const health = await apiCall('/api/health');
        if (health.status === 'ok') {
            statusBarItem.text = `$(book) Ceph Docs: ${health.total_chunks} chunks`;
            statusBarItem.tooltip = `Ceph ${health.ceph_version} | ${Object.keys(health.components).length} components | ${health.total_code_examples} examples`;
            statusBarItem.backgroundColor = undefined;
        } else {
            statusBarItem.text = '$(warning) Ceph Docs: No index';
            statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
        }
    } catch {
        statusBarItem.text = '$(error) Ceph Docs: Offline';
        statusBarItem.tooltip = 'Cannot connect to ceph-doc-kb REST API';
        statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
    }
}

async function searchDocs() {
    const { defaultComponent } = getConfig();

    const query = await vscode.window.showInputBox({
        prompt: 'Search Ceph documentation',
        placeHolder: 'e.g. erasure coded pool configuration',
    });
    if (!query) return;

    let component = defaultComponent;
    if (!component) {
        try {
            const data = await apiCall('/api/components');
            const components = data.components || [];
            const items = [{ label: '$(globe) All Components', value: '' }];
            for (const c of components) {
                items.push({ label: `$(folder) ${c.name}`, description: `${c.chunk_count} chunks`, value: c.name });
            }
            const picked = await vscode.window.showQuickPick(items, { placeHolder: 'Scope search to a component (or search all)' });
            if (!picked) return;
            component = picked.value;
        } catch {
            // Fall through to global search
        }
    }

    try {
        const params = { query, limit: 10 };
        if (component) params.component = component;
        const data = await apiCall('/api/search', params);
        const results = data.results || [];

        if (results.length === 0) {
            vscode.window.showInformationMessage('No documentation found for that query.');
            return;
        }

        const items = results.map(r => ({
            label: r.title,
            description: `${r.component}/${r.topic}`,
            detail: r.content ? r.content.substring(0, 120) + '...' : '',
            result: r,
        }));

        const picked = await vscode.window.showQuickPick(items, {
            placeHolder: `${results.length} results`,
            matchOnDetail: true,
        });

        if (picked) {
            outputChannel.clear();
            outputChannel.appendLine(`# ${picked.result.title}`);
            outputChannel.appendLine(`Source: ${picked.result.source_file}`);
            outputChannel.appendLine(`URL: ${picked.result.doc_url}`);
            outputChannel.appendLine(`Component: ${picked.result.component} | Topic: ${picked.result.topic}`);
            outputChannel.appendLine(`Score: ${picked.result.score.toFixed(3)}`);
            outputChannel.appendLine('---');
            outputChannel.appendLine(picked.result.content);
            outputChannel.show(true);
        }
    } catch (err) {
        vscode.window.showErrorMessage(`Ceph Docs search failed: ${err.message}`);
    }
}

async function searchExamples() {
    const { defaultComponent } = getConfig();

    const query = await vscode.window.showInputBox({
        prompt: 'Search Ceph code examples',
        placeHolder: 'e.g. ceph osd pool create',
    });
    if (!query) return;

    try {
        const params = { query, limit: 10 };
        if (defaultComponent) params.component = defaultComponent;
        const data = await apiCall('/api/examples', params);
        const results = data.results || [];

        if (results.length === 0) {
            vscode.window.showInformationMessage('No code examples found.');
            return;
        }

        const items = results.map(r => ({
            label: `$(code) [${r.language}] ${r.code.split('\n')[0].substring(0, 60)}`,
            description: r.component,
            detail: r.context ? r.context.substring(0, 100) : r.section_title,
            result: r,
        }));

        const picked = await vscode.window.showQuickPick(items, {
            placeHolder: `${results.length} code examples`,
            matchOnDetail: true,
        });

        if (picked) {
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                editor.edit(editBuilder => {
                    editBuilder.insert(editor.selection.active, picked.result.code);
                });
            } else {
                outputChannel.clear();
                outputChannel.appendLine(`# Code Example [${picked.result.language}]`);
                outputChannel.appendLine(`Source: ${picked.result.source_file}`);
                outputChannel.appendLine('---');
                outputChannel.appendLine(picked.result.code);
                outputChannel.show(true);
            }
        }
    } catch (err) {
        vscode.window.showErrorMessage(`Ceph Docs example search failed: ${err.message}`);
    }
}

async function findDocsForCommand() {
    const editor = vscode.window.activeTextEditor;
    let command = '';

    if (editor && !editor.selection.isEmpty) {
        command = editor.document.getText(editor.selection).trim();
    }

    if (!command) {
        command = await vscode.window.showInputBox({
            prompt: 'Enter a Ceph command to find documentation for',
            placeHolder: 'e.g. ceph osd pool create',
        });
    }
    if (!command) return;

    try {
        const data = await apiCall(`/api/command/${encodeURIComponent(command)}`);
        const refs = data.references || [];

        if (refs.length === 0) {
            vscode.window.showInformationMessage(`No documentation found for: ${command}`);
            return;
        }

        const items = refs.map(r => ({
            label: r.title,
            description: `${r.component}/${r.source}`,
            result: r,
        }));

        const picked = await vscode.window.showQuickPick(items, {
            placeHolder: `${refs.length} documentation references for "${command}"`,
        });

        if (picked) {
            // Fetch the full page
            const pageData = await apiCall(`/api/doc/${picked.result.source}`);
            if (pageData.sections) {
                outputChannel.clear();
                outputChannel.appendLine(`# ${picked.result.source}`);
                outputChannel.appendLine(`Sections: ${pageData.section_count}`);
                outputChannel.appendLine('---');
                for (const section of pageData.sections) {
                    outputChannel.appendLine(`\n## ${section.title}`);
                    outputChannel.appendLine(section.content);
                }
                outputChannel.show(true);
            }
        }
    } catch (err) {
        vscode.window.showErrorMessage(`Command doc lookup failed: ${err.message}`);
    }
}

async function getDocPage() {
    const sourcePath = await vscode.window.showInputBox({
        prompt: 'Enter the RST source path',
        placeHolder: 'e.g. rados/operations/pools.rst',
    });
    if (!sourcePath) return;

    try {
        const data = await apiCall(`/api/doc/${sourcePath}`);
        if (data.error) {
            vscode.window.showWarningMessage(data.error);
            return;
        }

        outputChannel.clear();
        outputChannel.appendLine(`# ${sourcePath}`);
        outputChannel.appendLine(`Sections: ${data.section_count}`);
        outputChannel.appendLine('===');
        for (const section of data.sections) {
            outputChannel.appendLine(`\n## ${section.title}`);
            outputChannel.appendLine(`Path: ${section.section_path}`);
            outputChannel.appendLine('---');
            outputChannel.appendLine(section.content);
        }
        outputChannel.show(true);
    } catch (err) {
        vscode.window.showErrorMessage(`Failed to get doc page: ${err.message}`);
    }
}

async function listComponents() {
    try {
        const data = await apiCall('/api/components');
        const components = data.components || [];

        const items = components.map(c => ({
            label: `$(folder) ${c.name}`,
            description: `${c.chunk_count} chunks, ${c.code_example_count} examples`,
            detail: `${c.topic_count} topics`,
        }));

        await vscode.window.showQuickPick(items, {
            placeHolder: `${components.length} components indexed`,
        });
    } catch (err) {
        vscode.window.showErrorMessage(`Failed to list components: ${err.message}`);
    }
}

function activate(context) {
    outputChannel = vscode.window.createOutputChannel('Ceph Documentation');

    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 50);
    statusBarItem.command = 'ceph-doc-kb.searchDocs';
    statusBarItem.text = '$(book) Ceph Docs';
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);

    updateStatusBar();
    const healthInterval = setInterval(updateStatusBar, 30000);
    context.subscriptions.push({ dispose: () => clearInterval(healthInterval) });

    context.subscriptions.push(
        vscode.commands.registerCommand('ceph-doc-kb.searchDocs', searchDocs),
        vscode.commands.registerCommand('ceph-doc-kb.searchExamples', searchExamples),
        vscode.commands.registerCommand('ceph-doc-kb.findDocsForCommand', findDocsForCommand),
        vscode.commands.registerCommand('ceph-doc-kb.getDocPage', getDocPage),
        vscode.commands.registerCommand('ceph-doc-kb.listComponents', listComponents),
    );
}

function deactivate() {}

module.exports = { activate, deactivate };
