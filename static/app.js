// ==================== THƯ VIỆN BÀI TẬP ====================
async function initProblemLibrary() {
    const grid = document.querySelector('#library-grid');
    if (!grid) return;
    const search = document.querySelector('#library-search');
    const category = document.querySelector('#library-category');
    const difficulty = document.querySelector('#library-difficulty');
    const sort = document.querySelector('#library-sort');
    const count = document.querySelector('#library-result-count');
    const total = document.querySelector('#library-total');
    let items = [], activeCategory = '', activeDifficulty = '', activeTag = '';

    function facets(id, values, type) {
        const el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = values.map(value => {
            const active = type === 'category' ? activeCategory === value : type === 'difficulty' ? activeDifficulty === value : activeTag === value;
            const n = items.filter(p => type === 'category' ? p.category === value : type === 'difficulty' ? p.difficulty === value : (p.tags || []).includes(value)).length;
            return `<button type="button" class="library-facet ${active ? 'active' : ''}" data-value="${escapeHtml(value)}"><span>${escapeHtml(value)}</span><b>${n}</b></button>`;
        }).join('') || '<p class="muted">Chưa có dữ liệu.</p>';
        el.querySelectorAll('button').forEach(btn => btn.addEventListener('click', () => {
            const value = btn.dataset.value;
            if (type === 'category') { activeCategory = activeCategory === value ? '' : value; category.value = activeCategory; }
            if (type === 'difficulty') { activeDifficulty = activeDifficulty === value ? '' : value; difficulty.value = activeDifficulty; }
            if (type === 'tag') activeTag = activeTag === value ? '' : value;
            render();
        }));
    }

    function render() {
        const q = (search.value || '').trim().toLocaleLowerCase('vi');
        const rows = items.filter(p => {
            const hay = [p.id, p.title, p.category, p.difficulty, ...(p.tags || [])].join(' ').toLocaleLowerCase('vi');
            return (!q || hay.includes(q)) && (!activeCategory || p.category === activeCategory)
                && (!activeDifficulty || p.difficulty === activeDifficulty) && (!activeTag || (p.tags || []).includes(activeTag));
        });
        rows.sort((a,b) => sort.value === 'score' ? (Number(b.total_score)||0)-(Number(a.total_score)||0)
            : String(a[sort.value] ?? '').localeCompare(String(b[sort.value] ?? ''),'vi',{numeric:true,sensitivity:'base'}));
        count.textContent = `Hiển thị ${rows.length} / ${items.length} bài`;
        grid.innerHTML = rows.length ? rows.map(p => `
            <article class="library-card">
                <div class="library-card-top"><span class="library-code">${escapeHtml(p.id)}</span><span class="library-difficulty">${escapeHtml(p.difficulty || 'Chưa phân loại')}</span></div>
                <h2><a href="/problems/${encodeURIComponent(p.id)}">${escapeHtml(p.title)}</a></h2>
                <div class="library-card-meta"><span>${escapeHtml(p.category || 'Khác')}</span><span>${Number(p.total_score)||0} điểm</span><span>${Number(p.subtasks_count)||0} subtask</span></div>
                <div class="library-card-tags">${(p.tags||[]).map(tag=>`<span>${escapeHtml(tag)}</span>`).join('')}</div>
                <a class="library-open" href="/problems/${encodeURIComponent(p.id)}">Mở bài <span>→</span></a>
            </article>`).join('') : '<div class="glass-card library-empty">Không tìm thấy bài phù hợp. Hãy đổi bộ lọc hoặc từ khóa.</div>';
        facets('library-categories',[...new Set(items.map(p=>p.category).filter(Boolean))].sort(),'category');
        facets('library-difficulties',[...new Set(items.map(p=>p.difficulty).filter(Boolean))].sort(),'difficulty');
        facets('library-tags',[...new Set(items.flatMap(p=>p.tags||[]))].sort(),'tag');
    }
    try {
        items = await api('/api/problems');
        total.textContent = items.length;
        [...new Set(items.map(p=>p.category).filter(Boolean))].sort().forEach(v=>category.add(new Option(v,v)));
        [...new Set(items.map(p=>p.difficulty).filter(Boolean))].sort().forEach(v=>difficulty.add(new Option(v,v)));
        search.addEventListener('input',render);
        category.addEventListener('change',()=>{activeCategory=category.value;render();});
        difficulty.addEventListener('change',()=>{activeDifficulty=difficulty.value;render();});
        sort.addEventListener('change',render);
        document.querySelector('#library-reset').addEventListener('click',()=>{
            search.value='';category.value='';difficulty.value='';sort.value='id';
            activeCategory='';activeDifficulty='';activeTag='';render();
        });
        render();
    } catch(e) {
        grid.innerHTML = `<div class="glass-card library-empty">Không tải được thư viện: ${escapeHtml(e.message)}</div>`;
        count.textContent='Lỗi tải dữ liệu';
    }
}
document.addEventListener('DOMContentLoaded', initProblemLibrary);

// ==================== API ====================

const pendingGetRequests = new Map();

async function api(url, opts = {}) {
    const method = (opts.method || 'GET').toUpperCase();
    const headers = { ...(opts.headers || {}) };

    if (opts.body && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
    }

    if (method === 'GET' && pendingGetRequests.has(url)) {
        return pendingGetRequests.get(url);
    }

    const request = (async () => {
        const r = await fetch(url, {
            credentials: 'same-origin',
            ...opts,
            headers
        });

        let data = {};

        try {
            data = await r.json();
        } catch {}

        if (!r.ok) {
            throw Error(data.error || `HTTP ${r.status}`);
        }

        return data;
    })();

    if (method !== 'GET') return request;

    pendingGetRequests.set(url, request);

    try {
        return await request;
    } finally {
        if (pendingGetRequests.get(url) === request) {
            pendingGetRequests.delete(url);
        }
    }
}

// ==================== TIỆN ÍCH ====================

function note(message) {
    const el = document.querySelector('#notice');
    if (el) el.textContent = message;
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[c]));
}

function formatScore(value) {
    const number = Number(value);
    return Number.isFinite(number) ? escapeHtml(number) : '0';
}

// Tiến độ của tài khoản hiện tại trên ngân hàng bài tập.
let mySolvedProblems = {};

async function loadMyProgress() {
    const section = document.querySelector('#my-progress-section');
    if (!section) return;

    const solvedEl = document.querySelector('#progress-solved');
    const attemptedEl = document.querySelector('#progress-attempted');
    const totalEl = document.querySelector('#progress-total');
    const fill = document.querySelector('#progress-fill');
    const caption = document.querySelector('#progress-caption');

    try {
        const data = await api('/api/my-progress');
        mySolvedProblems = {};
        (data.problems || []).forEach(item => {
            mySolvedProblems[String(item.problem_id)] = item;
        });

        if (solvedEl) solvedEl.textContent = data.solved ?? 0;
        if (attemptedEl) attemptedEl.textContent = data.attempted ?? 0;
        if (totalEl) totalEl.textContent = data.total ?? 0;

        const percent = data.total > 0 ? Math.min(100, (data.solved / data.total) * 100) : 0;
        if (fill) fill.style.width = percent + '%';
        if (caption) caption.textContent = `Bạn đã hoàn thành ${data.solved} / ${data.total} bài (${percent.toFixed(1)}%).`;

        const problemEl = document.querySelector('#problems');
        if (problemEl && problemEl.dataset.items) {
            renderProblems(getFilteredProblems());
        }
    } catch (error) {
        if (caption) caption.textContent = 'Chưa thể tải tiến độ. Hãy tải lại trang sau.';
        console.error('Lỗi tải tiến độ:', error);
    }
}

// Bộ lọc nhiều tags: chỉ cần khớp ít nhất một tag đã chọn.
let selectedProblemTags = [];

// ==================== DANH SÁCH BÀI TẬP ====================

// Cột mặc định: mã bài, tăng dần.
let sortColumn = 'id';
let sortAscending = true;

// Tìm kiếm kết hợp với sắp xếp.
function getFilteredProblems() {
    const el = document.querySelector('#problems');
    if (!el) return [];

    let items = [];

    try {
        items = JSON.parse(el.dataset.items || '[]');
    } catch {
        return [];
    }

    const query = (
        document.querySelector('#search')?.value || ''
    ).trim().toLocaleLowerCase('vi');
    const category = document.querySelector('#filter-category')?.value || '';
    const difficulty = document.querySelector('#filter-difficulty')?.value || '';

    return items.filter(p => {
        const problemTags = Array.isArray(p.tags) ? p.tags : [];
        const matchesQuery = `${p.id ?? ''} ${p.title ?? ''} ${p.category ?? ''} ${p.difficulty ?? ''} ${problemTags.join(' ')}`
            .toLocaleLowerCase('vi')
            .includes(query);
        const matchesCategory = !category || String(p.category ?? '') === category;
        const matchesDifficulty = !difficulty || String(p.difficulty ?? '') === difficulty;
        const matchesTags = !selectedProblemTags.length ||
            selectedProblemTags.some(tag => problemTags.includes(tag));
        return matchesQuery && matchesCategory && matchesDifficulty && matchesTags;
    });
}

function renderProblems(items) {
    const el = document.querySelector('#problems');
    if (!el) return;

    const columns = [
        ['id', 'Mã bài'],
        ['title', 'Tên bài'],
        ['category', 'Chủ đề'],
        ['difficulty', 'Độ khó'],
        ['tags', 'Tags thuật toán'],
        ['total_score', 'Điểm'],
        ['status', 'Trạng thái']
    ];

    const sorted = [...items].sort((a, b) => {
        let x = a[sortColumn] ?? '';
        let y = b[sortColumn] ?? '';

        if (sortColumn === 'total_score') {
            x = Number(x) || 0;
            y = Number(y) || 0;
            return sortAscending ? x - y : y - x;
        }

        if (sortColumn === 'status') {
            x = mySolvedProblems[String(a.id)]?.solved ? 2
                : mySolvedProblems[String(a.id)] ? 1 : 0;
            y = mySolvedProblems[String(b.id)]?.solved ? 2
                : mySolvedProblems[String(b.id)] ? 1 : 0;
            return sortAscending ? x - y : y - x;
        }

        const result = String(x).localeCompare(
            String(y),
            'vi',
            { numeric: true, sensitivity: 'base' }
        );
        return sortAscending ? result : -result;
    });

    const resultCount = document.querySelector('#problem-result-count');
    if (resultCount) {
        let total = 0;
        try { total = JSON.parse(el.dataset.items || '[]').length; } catch {}
        resultCount.textContent = `Hiển thị ${sorted.length} / ${total} bài tập`;
    }

    if (!sorted.length) {
        el.innerHTML = '<div class="problem-empty">Không tìm thấy bài phù hợp. Hãy thử đổi từ khóa hoặc bộ lọc.</div>';
        return;
    }

    el.innerHTML = `
        <div style="overflow-x:auto">
            <table>
                <thead>
                    <tr>
                        ${columns.map(([key, label]) => `
                            <th>
                                <button
                                    type="button"
                                    class="text-link sort-problems"
                                    data-column="${key}"
                                    style="font:inherit;cursor:pointer"
                                >
                                    ${label}
                                    ${
                                        sortColumn === key
                                            ? (sortAscending ? ' ↑' : ' ↓')
                                            : ' ↕'
                                    }
                                </button>
                            </th>
                        `).join('')}
                    </tr>
                </thead>

                <tbody>
                    ${sorted.map(p => `
                        <tr>
                            <td>
                                <a
                                    class="text-link"
                                    href="/problems/${encodeURIComponent(p.id ?? '')}"
                                >
                                    ${escapeHtml(p.id)}
                                </a>
                            </td>

                            <td>
                                <a
                                    class="text-link"
                                    href="/problems/${encodeURIComponent(p.id ?? '')}"
                                >
                                    ${escapeHtml(p.title)}
                                </a>
                            </td>

                            <td>${escapeHtml(p.category)}</td>
                            <td>${escapeHtml(p.difficulty)}</td>
                            <td><div class="problem-tags">${(Array.isArray(p.tags) ? p.tags : []).map(tag => `<span class="problem-tag">${escapeHtml(tag)}</span>`).join('')}</div></td>
                            <td>${formatScore(p.total_score)}</td>
                            <td>
                                ${mySolvedProblems[String(p.id)]?.solved
                                    ? '<span class="problem-status solved">✓ Đã FULL</span>'
                                    : mySolvedProblems[String(p.id)]
                                        ? '<span class="problem-status attempted">Đã thử</span>'
                                        : '<span class="problem-status unsolved">Chưa làm</span>'}
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;

    // Bấm tiêu đề để đổi cột sắp xếp.
    el.querySelectorAll('.sort-problems').forEach(button => {
        button.addEventListener('click', () => {
            const column = button.dataset.column;

            if (sortColumn === column) {
                sortAscending = !sortAscending;
            } else {
                sortColumn = column;
                sortAscending = true;
            }

            renderProblems(getFilteredProblems());
        });
    });
}

// ==================== BẢNG BÀI NỘP ====================

function renderSubmissionTable(items) {
    const el = document.querySelector('#submission-table');
    if (!el) return;

    if (!items.length) {
        el.innerHTML = '<p>Chưa có bài nộp.</p>';
        return;
    }

    el.innerHTML = `
        <div style="overflow-x:auto">
            <table>
                <thead>
                    <tr>
                        <th>Mã bài nộp</th>
                        <th>Bài tập</th>
                        <th>Kết quả</th>
                        <th>Điểm</th>
                        <th>Thời gian</th>
                    </tr>
                </thead>

                <tbody>
                    ${items.map(x => `
                        <tr>
                            <td>
                                ${escapeHtml(x.id ?? x.submission_id ?? '—')}
                            </td>

                            <td>
                                <a
                                    class="text-link"
                                    href="/problems/${encodeURIComponent(x.problem_id ?? '')}"
                                >
                                    ${escapeHtml(x.problem_id ?? '—')}
                                </a>
                            </td>

                            <td>${escapeHtml(x.verdict ?? 'Đang chấm')}</td>

                            <td>
                                ${formatScore(x.score)}/${formatScore(x.max_score)}
                            </td>

                            <td>${escapeHtml(x.created_at ?? '—')}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

// ==================== TẢI DỮ LIỆU ====================


async function refresh() {
    const authSection = document.querySelector('#auth-section');
    const status = document.querySelector('#user-status');
    const logout = document.querySelector('#logout-button');
    const admin = document.querySelector('#admin-link');
    const history = document.querySelector('#history');
    const problems = document.querySelector('#problems');
    const count = document.querySelector('#problem-count');
    const adminCount = document.querySelector('#admin-problem-count');
    const rankings = document.querySelector('#rankings');
    const submissionTable = document.querySelector('#submission-table');

    const tasks = [];

    // Tài khoản và lịch sử.
    if (
        authSection || status || logout || admin ||
        history || submissionTable
    ) {
        tasks.push((async () => {
            try {
                const me = await api('/api/me');
                const user = me.user;

                if (authSection) {
                    authSection.style.display = user ? 'none' : 'grid';
                }

                if (status) {
                    status.textContent = user
                        ? `Xin chào, ${user.username}`
                        : 'Chưa đăng nhập';
                }

                if (logout) logout.hidden = !user;
                if (admin) admin.hidden = !(user && user.is_admin);

                if (!history && !submissionTable) return;

                if (!user) {
                    if (history) {
                        history.textContent =
                            'Vui lòng đăng nhập để xem lịch sử.';
                    }

                    if (submissionTable) {
                        submissionTable.textContent =
                            'Vui lòng đăng nhập để xem bài nộp.';
                    }

                    return;
                }

                const data = await api('/api/submissions');
                const items = Array.isArray(data)
                    ? data
                    : (data.submissions || []);

                renderSubmissionTable(items);

                if (history) {
                    history.innerHTML = items.length
                        ? `
                            <div style="overflow-x:auto">
                                <table>
                                    <thead>
                                        <tr>
                                            <th>Bài</th>
                                            <th>Kết quả</th>
                                            <th>Điểm</th>
                                            <th>Thời gian</th>
                                        </tr>
                                    </thead>

                                    <tbody>
                                        ${items.map(x => `
                                            <tr>
                                                <td>
                                                    <a
                                                        class="text-link"
                                                        href="/problems/${encodeURIComponent(x.problem_id ?? '')}"
                                                    >
                                                        ${escapeHtml(x.problem_id ?? '—')}
                                                    </a>
                                                </td>

                                                <td>
                                                    ${escapeHtml(x.verdict ?? '—')}
                                                </td>

                                                <td>
                                                    ${formatScore(x.score)}/${formatScore(x.max_score)}
                                                </td>

                                                <td>
                                                    ${escapeHtml(x.created_at ?? '—')}
                                                </td>
                                            </tr>
                                        `).join('')}
                                    </tbody>
                                </table>
                            </div>
                        `
                        : 'Chưa có bài nộp.';
                }
            } catch (e) {
                // Giữ nguyên trạng thái đăng nhập do Flask render.
                console.error('Lỗi tải tài khoản:', e);
            }
        })());
    }

    // Danh sách bài tập.
    if (problems || count || adminCount) {
        tasks.push(
            api('/api/problems').then(items => {
                if (!Array.isArray(items)) {
                    throw Error('Dữ liệu danh sách bài tập không hợp lệ.');
                }

                if (problems) {
                    problems.dataset.items = JSON.stringify(items);

                    const categories = [...new Set(items.map(p => String(p.category ?? '').trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'vi'));
                    const difficulties = [...new Set(items.map(p => String(p.difficulty ?? '').trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'vi', { numeric: true }));
                    const allTags = [...new Set(items.flatMap(p => Array.isArray(p.tags) ? p.tags : []))].sort((a, b) => a.localeCompare(b, 'vi'));
                    const tagContainer = document.querySelector('#filter-tags');
                    if (tagContainer) {
                        tagContainer.innerHTML = allTags.map(tag =>
                            `<button type="button" class="tag-filter-chip${selectedProblemTags.includes(tag) ? ' active' : ''}" data-tag="${escapeHtml(tag)}" aria-pressed="${selectedProblemTags.includes(tag)}">${escapeHtml(tag)}</button>`
                        ).join('');
                    }

                    const categorySelect = document.querySelector('#filter-category');
                    const difficultySelect = document.querySelector('#filter-difficulty');
                    if (categorySelect) {
                        const selected = categorySelect.value;
                        categorySelect.innerHTML = '<option value="">Tất cả chủ đề</option>' +
                            categories.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
                        categorySelect.value = selected;
                    }
                    if (difficultySelect) {
                        const selected = difficultySelect.value;
                        difficultySelect.innerHTML = '<option value="">Mọi độ khó</option>' +
                            difficulties.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
                        difficultySelect.value = selected;
                    }
                    renderProblems(getFilteredProblems());
                }

                if (count) {
                    count.textContent = items.length;
                }

                if (adminCount) {
                    adminCount.textContent =
                        `${items.length} bài đang được nạp từ ngân hàng dữ liệu.`;
                }
            }).catch(e => {
                console.error('Lỗi tải danh sách bài:', e);
                note(e.message);
            })
        );
    }

    // Bảng xếp hạng.
    if (rankings) {
        tasks.push(
            api('/api/leaderboard').then(rows => {
                rankings.innerHTML = rows.length
                    ? `
                        <div style="overflow-x:auto">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Hạng</th>
                                        <th>Thành viên</th>
                                        <th>Điểm</th>
                                        <th>Bài có điểm</th>
                                    </tr>
                                </thead>

                                <tbody>
                                    ${rows.map((x, i) => `
                                        <tr>
                                            <td>
                                                ${
                                                    i === 0 ? '🥇'
                                                    : i === 1 ? '🥈'
                                                    : i === 2 ? '🥉'
                                                    : i + 1
                                                }
                                            </td>

                                            <td>${escapeHtml(x.username)}</td>
                                            <td><b>${formatScore(x.score)}</b></td>
                                            <td>${formatScore(x.solved)}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    `
                    : 'Chưa có thành tích.';

            }).catch(e => console.error('Lỗi tải bảng xếp hạng:', e))
        );
    }

    await Promise.allSettled(tasks);
}


// ==================== TÌM KIẾM BÀI ====================

document.querySelector('#search')?.addEventListener('input', () => {
    renderProblems(getFilteredProblems());
});

// ==================== ĐĂNG NHẬP / ĐĂNG KÝ ====================

const loginForm = document.querySelector('#login-form');
const registerForm = document.querySelector('#register-form');

const loginBox = document.querySelector('#login-box');
const registerBox = document.querySelector('#register-box');

const loginTab = document.querySelector('#login-tab');
const registerTab = document.querySelector('#register-tab');

function showAuth(type) {
    const isLogin = type === 'login';

    if (loginBox) loginBox.hidden = !isLogin;
    if (registerBox) registerBox.hidden = isLogin;

    if (loginTab) loginTab.classList.toggle('active', isLogin);
    if (registerTab) registerTab.classList.toggle('active', !isLogin);

    const notice = document.querySelector('#notice');
    if (notice) notice.textContent = '';
}

loginTab?.addEventListener('click', () => showAuth('login'));
registerTab?.addEventListener('click', () => showAuth('register'));

loginForm?.addEventListener('submit', async e => {
    e.preventDefault();

    const button = loginForm.querySelector('button[type="submit"]');
    if (button) button.disabled = true;

    try {
        const data = await api('/api/login', {
            method: 'POST',
            body: JSON.stringify(
                Object.fromEntries(new FormData(loginForm))
            )
        });

        note(data.message || 'Đăng nhập thành công.');

        const next = document.querySelector('#login-next')?.value;

        // Chuyển đến trang người dùng muốn truy cập.
        location.href = next || '/';

    } catch (err) {
        note(err.message);
    } finally {
        if (button) button.disabled = false;
    }
});

registerForm?.addEventListener('submit', async e => {
    e.preventDefault();

    const button = registerForm.querySelector('button[type="submit"]');
    if (button) button.disabled = true;

    try {
        const data = await api('/api/register', {
            method: 'POST',
            body: JSON.stringify(
                Object.fromEntries(new FormData(registerForm))
            )
        });

        note(data.message || 'Đăng ký thành công.');

        registerForm.reset();
        showAuth('login');

    } catch (err) {
        note(err.message);
    } finally {
        if (button) button.disabled = false;
    }
});

// ==================== ĐĂNG XUẤT ====================

document.querySelector('#logout-button')?.addEventListener('click', async () => {
    try {
        await api('/api/logout', { method: 'POST' });
        location.href = '/';
    } catch (e) {
        note(e.message);
    }
});

// ==================== NỘP BÀI ====================

// Lưu trạng thái của từng bài nộp riêng biệt.
const activeSubmissions = new Map();

function renderSubmissionResults(result) {
    result.textContent = [...activeSubmissions.values()]
        .map(item =>
            item.id + '\n' + item.message
        )
        .join('\n\n------------------------------\n\n');
}

// Theo dõi một bài nộp độc lập.
async function watchSubmission(submissionId, result) {
    let delay = 500;
    let consecutiveErrors = 0;

    try {
        while (true) {
            await new Promise(resolve => setTimeout(resolve, delay));

            let data;

            try {
                data = await api(
                    `/api/submissions/${encodeURIComponent(submissionId)}/status`
                );

                consecutiveErrors = 0;
            } catch (err) {
                consecutiveErrors++;

                activeSubmissions.set(submissionId, {
                    id: 'Bài nộp #' + submissionId,
                    message:
                        `Đang chờ kết quả... (lỗi kết nối ${consecutiveErrors})`
                });

                renderSubmissionResults(result);

                if (consecutiveErrors >= 5) {
                    throw err;
                }

                delay = Math.min(delay * 2, 5000);
                continue;
            }

            const verdict = data.verdict;

            if (
                verdict &&
                verdict !== 'Queued' &&
                verdict !== 'Processing'
            ) {
                activeSubmissions.set(submissionId, {
                    id: 'Bài nộp #' + submissionId,
                    message:
                        `${verdict}\n` +
                        `Điểm: ${data.score}/${data.max_score}\n\n` +
                        JSON.stringify(data.details ?? {}, null, 2)
                });

                renderSubmissionResults(result);

                await refresh();
                return;
            }

            activeSubmissions.set(submissionId, {
                id: 'Bài nộp #' + submissionId,
                message: verdict === 'Queued'
                    ? 'Đang chờ đến lượt chấm...'
                    : 'Đang chấm bài...'
            });

            renderSubmissionResults(result);

            delay = Math.min(Math.round(delay * 1.3), 2000);
        }
    } catch (err) {
        activeSubmissions.set(submissionId, {
            id: 'Bài nộp #' + submissionId,
            message:
                'Chưa lấy được kết quả: ' + err.message +
                '\nBài nộp có thể vẫn đang được xử lý. Hãy kiểm tra lịch sử bài nộp.'
        });

        renderSubmissionResults(result);
    }
}

document.querySelector('#submit')?.addEventListener('click', async e => {
    const button = e.currentTarget;
    const result = document.querySelector('#result');
    const source = document.querySelector('#source');
    const language = document.querySelector('#language');

    if (!result || !source || !language) {
        note('Không tìm thấy vùng nhập code hoặc vùng hiển thị kết quả.');
        return;
    }

    if (button.disabled) return;

    // Chỉ khóa nút trong lúc gửi yêu cầu.
    button.disabled = true;

    try {
        const data = await api('/api/submit', {
            method: 'POST',
            body: JSON.stringify({
                problem_id: button.dataset.problem,
                source_code: source.value,
                language_id: language.value
            })
        });

        if (!data.submission_id) {
            throw Error('Máy chủ chưa trả về mã bài nộp.');
        }

        activeSubmissions.set(data.submission_id, {
            id: 'Bài nộp #' + data.submission_id,
            message: 'Đã nhận bài. Đang chấm...'
        });

        renderSubmissionResults(result);

        // Không đợi bài này chấm xong mới cho nộp bài tiếp.
        watchSubmission(data.submission_id, result);

    } catch (err) {
        note('Không gửi được bài: ' + err.message);
    } finally {
        // Mở nút ngay sau khi máy chủ nhận bài.
        button.disabled = false;
    }
});

// ==================== THỐNG KÊ CÁ NHÂN ====================

async function loadMyAnalytics() {
    const root = document.querySelector('#profile-analytics');
    if (!root) return;

    const noteEl = document.querySelector('#analytics-note');
    try {
        const data = await api('/api/my-analytics');
        const setText = (id, value) => {
            const el = document.querySelector('#' + id);
            if (el) el.textContent = value;
        };
        setText('analytics-solved', data.total_solved ?? 0);
        setText('analytics-attempted', data.total_attempted ?? 0);
        setText('analytics-submissions', data.total_submissions ?? 0);
        setText('analytics-rate', (data.full_rate ?? 0) + '%');

        const daily = document.querySelector('#analytics-daily');
        if (daily) {
            const values = data.daily || [];
            const max = Math.max(1, ...values.map(item => Number(item.count) || 0));
            daily.innerHTML = values.map(item => {
                const count = Number(item.count) || 0;
                const height = Math.max(4, count / max * 100);
                return `<div class="daily-column" title="${escapeHtml(item.date)}: ${count} lượt nộp">
                    <span class="daily-value">${count || ''}</span>
                    <i style="height:${height}%"></i>
                    <small>${escapeHtml(item.date.slice(5))}</small>
                </div>`;
            }).join('');
        }

        const categories = document.querySelector('#analytics-categories');
        if (categories) {
            const rows = data.categories || [];
            categories.innerHTML = rows.length ? rows.map(item => {
                const ratio = item.attempted ? item.solved / item.attempted * 100 : 0;
                return `<div class="category-row">
                    <div><b>${escapeHtml(item.category)}</b><span>${item.solved}/${item.attempted} FULL</span></div>
                    <div class="category-track"><i style="width:${ratio}%"></i></div>
                </div>`;
            }).join('') : '<p class="muted">Chưa có dữ liệu. Hãy thử giải một bài nhé!</p>';
        }

        const tags = document.querySelector('#analytics-tags');
        if (tags) {
            const rows = data.tags || [];
            tags.innerHTML = rows.length ? rows.map(item =>
                `<span class="analytics-tag">${escapeHtml(item.tag)} <b>${item.solved}</b></span>`
            ).join('') : '<p class="muted">Chưa có tags nào được chinh phục.</p>';
        }

        const verdicts = document.querySelector('#analytics-verdicts');
        if (verdicts) {
            const rows = data.verdicts || [];
            verdicts.innerHTML = rows.length ? rows.map(item =>
                `<div class="verdict-row"><span>${escapeHtml(item.verdict)}</span><b>${item.count}</b></div>`
            ).join('') : '<p class="muted">Chưa có lượt nộp nào.</p>';
        }

        if (noteEl) noteEl.textContent = 'Thống kê tính cả bài luyện tập và bài trong contest; lịch sử lấy tối đa 500 lượt nộp gần nhất.';
    } catch (err) {
        if (noteEl) noteEl.textContent = 'Không tải được thống kê: ' + err.message;
    }
}

// ==================== HỒ SƠ ====================

async function loadProfile() {
    loadMyAnalytics();
    const form = document.querySelector('#profile-form');
    if (!form) return;

    try {
        const data = await api('/api/me');
        const user = data.user;
        const details = document.querySelector('#profile-details');

        if (!user) {
            if (details) {
                details.textContent = 'Vui lòng đăng nhập trước.';
            }

            const button = form.querySelector('button');
            if (button) button.disabled = true;

            return;
        }

        const bio = form.elements.namedItem('bio');
        const color = form.elements.namedItem('avatar_color');

        if (bio) bio.value = user.bio || '';
        if (color) color.value = user.avatar_color || '#168BFF';

        const avatar = document.querySelector('#profile-avatar');

        if (avatar) {
            avatar.textContent = user.username.slice(0, 2).toUpperCase();
            avatar.style.background = user.avatar_color || '#168BFF';
        }

        if (details) {
            details.innerHTML = `
                <p>
                    <b>Tên đăng nhập:</b>
                    ${escapeHtml(user.username)}
                </p>

                <p>
                    <b>Vai trò:</b>
                    ${user.is_admin ? 'Quản trị viên' : 'Học sinh'}
                </p>

                <p>
                    <b>Trạng thái:</b>
                    ${user.approved ? 'Đã duyệt' : 'Chờ duyệt'}
                </p>

                <p>
                    <b>Ngày tạo:</b>
                    ${escapeHtml(user.created_at || '')}
                </p>
            `;
        }

        const button = form.querySelector('button');
        if (button) button.disabled = false;

    } catch (err) {
        const details = document.querySelector('#profile-details');
        if (details) details.textContent = err.message;
    }
}

document.querySelector('#profile-form')?.addEventListener('submit', async e => {
    e.preventDefault();

    const form = e.currentTarget;
    const output = document.querySelector('#profile-notice');
    const bio = form.elements.namedItem('bio');
    const color = form.elements.namedItem('avatar_color');

    try {
        await api('/api/profile', {
            method: 'PUT',
            body: JSON.stringify({
                bio: bio ? bio.value : '',
                avatar_color: color ? color.value : '#168BFF'
            })
        });

        if (output) output.textContent = 'Đã lưu hồ sơ.';

        const avatar = document.querySelector('#profile-avatar');
        if (avatar && color) {
            avatar.style.background = color.value;
        }

        await loadProfile();

    } catch (err) {
        if (output) output.textContent = err.message;
    }
});

document.querySelector('#avatar_color')?.addEventListener('input', e => {
    const avatar = document.querySelector('#profile-avatar');
    if (avatar) avatar.style.background = e.target.value;
});

// ==================== QUẢN TRỊ VIÊN ====================

async function loadAdmin() {
    const el = document.querySelector('#admin-users');
    if (!el) return;

    try {
        const users = await api('/api/admin/users');

        el.innerHTML = users.length
            ? users.map(user => `
                <div class="admin-user">
                    <div>
                        <b>${escapeHtml(user.username)}</b>

                        <small>
                            ${user.approved ? 'Đã duyệt' : 'Đang chờ duyệt'}
                            · ${escapeHtml(user.created_at)}
                        </small>
                    </div>

                    ${
                        user.approved
                            ? '<span class="pill pill-blue">Đã duyệt</span>'
                            : `
                                <button
                                    class="button button-primary approve-user"
                                    data-id="${escapeHtml(user.id)}"
                                >
                                    Duyệt tài khoản
                                </button>
                            `
                    }
                </div>
            `).join('')
            : 'Không có yêu cầu tài khoản.';

        el.querySelectorAll('.approve-user').forEach(button => {
            button.addEventListener('click', async () => {
                button.disabled = true;

                try {
                    await api(
                        `/api/admin/users/${encodeURIComponent(button.dataset.id)}/approve`,
                        { method: 'POST' }
                    );

                    await loadAdmin();

                } catch (err) {
                    alert(err.message);
                    button.disabled = false;
                }
            });
        });

    } catch (err) {
        el.textContent = err.message;
    }
}

document.querySelector('#reload-users')?.addEventListener('click', loadAdmin);

document.querySelector('#refresh-submissions')
    ?.addEventListener('click', async e => {
        const button = e.currentTarget;
        button.disabled = true;

        try {
            await refresh();
        } finally {
            button.disabled = false;
        }
    });

// Bộ lọc kho bài tập.
['#search', '#filter-category', '#filter-difficulty'].forEach(selector => {
    document.querySelector(selector)?.addEventListener(
        selector === '#search' ? 'input' : 'change',
        () => renderProblems(getFilteredProblems())
    );
});

document.querySelector('#filter-tags')?.addEventListener('click', event => {
    const button = event.target.closest('[data-tag]');
    if (!button) return;
    const tag = button.dataset.tag;
    selectedProblemTags = selectedProblemTags.includes(tag)
        ? selectedProblemTags.filter(item => item !== tag)
        : [...selectedProblemTags, tag];
    document.querySelectorAll('#filter-tags [data-tag]').forEach(item => {
        const active = selectedProblemTags.includes(item.dataset.tag);
        item.classList.toggle('active', active);
        item.setAttribute('aria-pressed', String(active));
    });
    renderProblems(getFilteredProblems());
});

document.querySelector('#reset-problem-filters')?.addEventListener('click', () => {
    const search = document.querySelector('#search');
    const category = document.querySelector('#filter-category');
    const difficulty = document.querySelector('#filter-difficulty');
    if (search) search.value = '';
    if (category) category.value = '';
    if (difficulty) difficulty.value = '';
    selectedProblemTags = [];
    document.querySelectorAll('#filter-tags [data-tag]').forEach(item => {
        item.classList.remove('active');
        item.setAttribute('aria-pressed', 'false');
    });
    renderProblems(getFilteredProblems());
});

document.querySelector('#random-problem')?.addEventListener('click', () => {
    const items = getFilteredProblems();
    if (!items.length) {
        note('Không có bài tập phù hợp để chọn ngẫu nhiên.');
        return;
    }
    const selected = items[Math.floor(Math.random() * items.length)];
    window.location.href = `/problems/${encodeURIComponent(selected.id ?? '')}`;
});

// ==================== KHỞI ĐỘNG ====================

Promise.allSettled([
    refresh(),
    loadProfile(),
    loadAdmin(),
    loadMyProgress()
]);
