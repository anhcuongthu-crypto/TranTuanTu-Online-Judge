// Library page is rendered by its page-local script in templates/library.html.

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

async function loadMyProgress(force = false) {
    // Trang danh sách bài tập không có progress section riêng;
    // vẫn phải tải tiến độ để render trạng thái từng bài.
    const solvedEl = document.querySelector('#progress-solved');
    const attemptedEl = document.querySelector('#progress-attempted');
    const totalEl = document.querySelector('#progress-total');
    const fill = document.querySelector('#progress-fill');
    const caption = document.querySelector('#progress-caption');

    try {
        const data = await api(
            force ? '/api/my-progress?fresh=1' : '/api/my-progress'
        );
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

// ==================== DANH SÁCH BÀI TẬP ====================

// Danh sách bài đã lưu chỉ nằm trên trình duyệt hiện tại.
const SAVED_PROBLEMS_KEY = 'trantu-oj:saved-problems:v1';
const anonymousSavedProblemIds = new Set();
const savedProblemIds = new Set();
let savedProblemsUserId = null;

try {
    const stored = JSON.parse(localStorage.getItem(SAVED_PROBLEMS_KEY) || '[]');
    if (Array.isArray(stored)) {
        stored.forEach(id => {
            anonymousSavedProblemIds.add(String(id));
            savedProblemIds.add(String(id));
        });
    }
} catch {}

function persistAnonymousSavedProblems() {
    try {
        localStorage.setItem(
            SAVED_PROBLEMS_KEY,
            JSON.stringify([...anonymousSavedProblemIds])
        );
    } catch (error) {
        console.warn('Không thể lưu danh sách bài yêu thích trên trình duyệt:', error);
    }
}

function showAnonymousSavedProblems() {
    savedProblemIds.clear();
    anonymousSavedProblemIds.forEach(id => savedProblemIds.add(id));
    renderSavedProblemChanges();
}

function renderSavedProblemChanges() {
    const problemEl = document.querySelector('#problems');
    if (problemEl?.dataset.items) {
        problemPage = 1;
        renderProblems(getFilteredProblems());
    }
}

async function syncSavedProblemsWithAccount(user) {
    if (!user?.id) {
        if (savedProblemsUserId !== null) {
            savedProblemsUserId = null;
            showAnonymousSavedProblems();
        }
        return;
    }

    const targetUserId = String(user.id);
    if (savedProblemsUserId === targetUserId) return;

    // Không để dấu sao của tài khoản trước xuất hiện trong tài khoản mới.
    savedProblemsUserId = targetUserId;
    showAnonymousSavedProblems();

    try {
        // Chỉ chuyển danh sách ẩn danh lên tài khoản; không lấy dữ liệu
        // của tài khoản trước từ Set đang hiển thị.
        const anonymousIds = [...anonymousSavedProblemIds];
        if (anonymousIds.length) {
            await api('/api/saved-problems', {
                method: 'POST',
                body: JSON.stringify({
                    problem_ids: anonymousIds,
                    saved: true
                })
            });
        }

        const remote = await api('/api/saved-problems');
        if (savedProblemsUserId !== targetUserId) return;

        const remoteIds = Array.isArray(remote.problem_ids)
            ? remote.problem_ids.map(String)
            : [];

        anonymousSavedProblemIds.clear();
        persistAnonymousSavedProblems();

        savedProblemIds.clear();
        remoteIds.forEach(id => savedProblemIds.add(id));
        renderSavedProblemChanges();
    } catch (error) {
        // Giữ lại mục ẩn danh nếu mạng lỗi; không ghi đè dữ liệu tài khoản.
        console.warn('Chưa thể đồng bộ bài đã lưu:', error);
    }
}

function toggleSavedProblem(problemId) {
    const id = String(problemId ?? '');
    if (!id) return;
    const saved = !savedProblemIds.has(id);

    if (saved) savedProblemIds.add(id);
    else savedProblemIds.delete(id);

    if (savedProblemsUserId) {
        api('/api/saved-problems', {
            method: 'POST',
            body: JSON.stringify({ problem_id: id, saved })
        }).catch(error => {
            console.warn('Chưa thể đồng bộ thay đổi bài đã lưu:', error);
        });
    } else {
        if (saved) anonymousSavedProblemIds.add(id);
        else anonymousSavedProblemIds.delete(id);
        persistAnonymousSavedProblems();
    }

    renderSavedProblemChanges();
}

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
    const status = document.querySelector('#filter-status')?.value || '';
    const savedOnly = !!document.querySelector('#filter-saved')?.checked;

    return items.filter(p => {
        const matchesQuery = `${p.id ?? ''} ${p.title ?? ''} ${p.category ?? ''} ${p.difficulty ?? ''}`
            .toLocaleLowerCase('vi')
            .includes(query);
        const matchesCategory = !category || String(p.category ?? '') === category;
        const matchesDifficulty = !difficulty || String(p.difficulty ?? '') === difficulty;
        const progress = mySolvedProblems[String(p.id)];
        const actualStatus = progress?.solved ? 'solved' : progress ? 'attempted' : 'unsolved';
        const matchesStatus = !status || actualStatus === status;
        const matchesSaved = !savedOnly || savedProblemIds.has(String(p.id));
        return matchesQuery && matchesCategory && matchesDifficulty && matchesStatus && matchesSaved;
    });
}

let problemPage = 1;
let problemPageSize = 25;

function renderProblems(items) {
    const el = document.querySelector('#problems');
    if (!el) return;

    const columns = [
        ['id', 'Mã bài'],
        ['title', 'Bài tập'],
        ['category', 'Chủ đề'],
        ['difficulty', 'Độ khó'],
        ['total_score', 'Điểm'],
        ['status', 'Trạng thái']
    ];

    const sorted = [...items].sort((a, b) => {
        let x = a[sortColumn] ?? '';
        let y = b[sortColumn] ?? '';
        if (sortColumn === 'total_score') {
            x = Number(x) || 0; y = Number(y) || 0;
            return sortAscending ? x - y : y - x;
        }
        if (sortColumn === 'status') {
            x = mySolvedProblems[String(a.id)]?.solved ? 2 : mySolvedProblems[String(a.id)] ? 1 : 0;
            y = mySolvedProblems[String(b.id)]?.solved ? 2 : mySolvedProblems[String(b.id)] ? 1 : 0;
            return sortAscending ? x - y : y - x;
        }
        const result = String(x).localeCompare(String(y), 'vi', {numeric:true, sensitivity:'base'});
        return sortAscending ? result : -result;
    });

    const total = (() => { try { return JSON.parse(el.dataset.items || '[]').length; } catch { return 0; } })();
    const count = document.querySelector('#problem-result-count');
    if (count) count.textContent = `Hiển thị ${sorted.length} / ${total} bài tập`;

    const pages = Math.max(1, Math.ceil(sorted.length / problemPageSize));
    problemPage = Math.min(problemPage, pages);
    const from = (problemPage - 1) * problemPageSize;
    const visible = sorted.slice(from, from + problemPageSize);

    if (!sorted.length) {
        el.innerHTML = '<div class="problemset-empty"><strong>Không tìm thấy bài tập</strong><span>Thử thay đổi từ khóa hoặc bộ lọc để xem thêm kết quả.</span></div>';
    } else {
        el.innerHTML = `
            <div class="problemset-scroll">
                <table class="problemset-table">
                    <thead><tr>
                        ${columns.map(([key,label]) => `<th><button type="button" class="problem-sort sort-problems" data-column="${key}">${label}<span>${sortColumn===key?(sortAscending?'↑':'↓'):'↕'}</span></button></th>`).join('')}<th scope="col">Đánh dấu</th>
                    </tr></thead>
                    <tbody>
                        ${visible.map(p => {
                            const progress = mySolvedProblems[String(p.id)];
                            const solved = !!progress?.solved;
                            const attempted = !!progress && !solved;
                            const status = solved
                                ? '<span class="problem-pill is-solved">✓ Đã FULL</span>'
                                : attempted ? '<span class="problem-pill is-attempted">Đã thử</span>'
                                : '<span class="problem-pill is-unsolved">Chưa làm</span>';
                            return `<tr>
                                <td><a class="problem-id-link" href="/problems/${encodeURIComponent(p.id ?? '')}">${escapeHtml(p.id || '—')}</a></td>
                                <td><a class="problem-title-link" href="/problems/${encodeURIComponent(p.id ?? '')}">${escapeHtml(p.title || 'Chưa có tiêu đề')}</a><small>${escapeHtml(p.short_description || '')}</small></td>
                                <td><span class="problem-category-tag">${escapeHtml(p.category || 'Khác')}</span></td>
                                <td>${escapeHtml(p.difficulty || '—')}</td>
                                <td class="problem-points">${formatScore(p.total_score)}</td>
                                <td>${status}</td>
                                <td class="problem-save-cell"><button type="button" class="problem-save-btn ${savedProblemIds.has(String(p.id)) ? 'is-saved' : ''}" data-save-problem="${escapeHtml(p.id)}" aria-label="${savedProblemIds.has(String(p.id)) ? 'Bỏ lưu' : 'Lưu'} bài ${escapeHtml(p.id)}" aria-pressed="${savedProblemIds.has(String(p.id))}" title="${savedProblemIds.has(String(p.id)) ? 'Bỏ khỏi bài đã lưu' : 'Lưu để luyện lại'}">${savedProblemIds.has(String(p.id)) ? '★' : '☆'}</button></td>
                            </tr>`;
                        }).join('')}
                    </tbody>
                </table>
            </div>`;
    }

    const pagination = document.querySelector('#problem-pagination');
    if (pagination) {
        if (sorted.length <= problemPageSize) pagination.innerHTML = '';
        else {
            const button = (label, page, disabled, active=false) => `<button type="button" class="problem-page-btn ${active?'active':''}" data-page="${page}" ${disabled?'disabled':''}>${label}</button>`;
            const nums = [];
            const first = Math.max(1, problemPage - 2);
            const last = Math.min(pages, problemPage + 2);
            if (first > 1) nums.push(button('1',1,false), '<span class="problem-page-dots">…</span>');
            for (let p=first;p<=last;p++) nums.push(button(String(p),p,false,p===problemPage));
            if (last < pages) nums.push('<span class="problem-page-dots">…</span>',button(String(pages),pages,false));
            pagination.innerHTML = `<span class="problem-page-info">Trang ${problemPage} / ${pages}</span><div class="problem-page-actions">${button('←',problemPage-1,problemPage===1)}${nums.join('')}${button('→',problemPage+1,problemPage===pages)}</div>`;
            pagination.querySelectorAll('[data-page]').forEach(b => b.addEventListener('click', () => {
                problemPage = Number(b.dataset.page);
                renderProblems(getFilteredProblems());
                document.querySelector('#problem-section')?.scrollIntoView({behavior:'smooth',block:'start'});
            }));
        }
    }

    el.querySelectorAll('.sort-problems').forEach(button => button.addEventListener('click', () => {
        const column = button.dataset.column;
        if (sortColumn === column) sortAscending = !sortAscending;
        else { sortColumn = column; sortAscending = true; }
        problemPage = 1;
        renderProblems(getFilteredProblems());
    }));
    el.querySelectorAll('[data-save-problem]').forEach(button => button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        toggleSavedProblem(button.dataset.saveProblem);
    }));
}

// ==================== BẢNG BÀI NỘP ===================

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
                savedProblemsUserId = user?.id ? String(user.id) : null;
                if (user) syncSavedProblemsWithAccount(user);

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

                const data = await api('/api/submissions?limit=50');
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

                await Promise.allSettled([
                    refresh(),
                    loadMyProgress(true)
                ]);
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

        const achievements = document.querySelector('#analytics-achievements');
        if (achievements) {
            const rows = data.achievements || [];
            achievements.innerHTML = rows.length ? rows.map(item => {
                const target = Math.max(1, Number(item.target) || 1);
                const progress = Math.max(0, Math.min(target, Number(item.progress) || 0));
                const percent = progress / target * 100;
                return `<article class="achievement-card ${item.unlocked ? 'unlocked' : 'locked'}">
                    <span class="achievement-icon" aria-hidden="true">${escapeHtml(item.icon || '🏅')}</span>
                    <div>
                        <strong>${escapeHtml(item.name || 'Huy hiệu')}</strong>
                        <p>${escapeHtml(item.description || '')}</p>
                        <div class="achievement-progress" role="progressbar"
                             aria-valuenow="${progress}" aria-valuemin="0" aria-valuemax="${target}">
                            <i style="width:${percent}%"></i>
                        </div>
                        <span class="achievement-status">${item.unlocked ? '✓ Đã mở khóa' : `${progress}/${target}`}</span>
                    </div>
                </article>`;
            }).join('') : '<p class="muted">Chưa có huy hiệu để hiển thị.</p>';
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
['#search', '#filter-category', '#filter-difficulty', '#filter-status', '#filter-saved'].forEach(selector => {
    document.querySelector(selector)?.addEventListener(
        selector === '#search' ? 'input' : 'change',
        () => { problemPage = 1; renderProblems(getFilteredProblems()); }
    );
});

document.querySelector('#reset-problem-filters')?.addEventListener('click', () => {
    const search = document.querySelector('#search');
    const category = document.querySelector('#filter-category');
    const difficulty = document.querySelector('#filter-difficulty');
    if (search) search.value = '';
    if (category) category.value = '';
    const status = document.querySelector('#filter-status');
    const saved = document.querySelector('#filter-saved');
    if (difficulty) difficulty.value = '';
    if (status) status.value = '';
    if (saved) saved.checked = false;
    problemPage = 1;
    renderProblems(getFilteredProblems());
});

document.querySelector('#problem-page-size')?.addEventListener('change', event => {
    problemPageSize = Number(event.target.value) || 25;
    problemPage = 1;
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
