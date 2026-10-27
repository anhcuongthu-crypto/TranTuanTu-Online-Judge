
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

function renderProblems(items) {
    const el = document.querySelector('#problems');
    if (!el) return;

    el.innerHTML = items.map(p => `
        <a class="problem" href="/problems/${encodeURIComponent(p.id)}">
            <span class="problem-code">${escapeHtml(p.id)}</span>
            <span class="problem-title">${escapeHtml(p.title)}</span>
            <small>
                ${escapeHtml(p.category)} ·
                ${escapeHtml(p.difficulty)} ·
                ${formatScore(p.total_score)} điểm
            </small>
        </a>
    `).join('') ||
        '<div class="glass-card">Không tìm thấy bài phù hợp.</div>';
}

// ==================== TẢI DỮ LIỆU ====================

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
                            <td>${escapeHtml(x.id ?? x.submission_id ?? '—')}</td>
                            <td>
                                <a class="text-link"
                                   href="/problems/${encodeURIComponent(x.problem_id ?? '')}">
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

    const tasks = [];

    // Tài khoản và lịch sử.
    if (
    authSection || status || logout || admin ||
    history || document.querySelector('#submission-table')
) {
        tasks.push((async () => {
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

            
if (!history && !document.querySelector('#submission-table')) return;

if (!user) {
    if (history) {
        history.textContent = 'Vui lòng đăng nhập để xem lịch sử.';
    }

    const table = document.querySelector('#submission-table');
    if (table) {
        table.textContent = 'Vui lòng đăng nhập để xem bài nộp.';
    }
    return;
}


            
const items = await api('/api/submissions');

// Hiển thị bảng mới dưới khu vực chọn bài.
renderSubmissionTable(items);

// Giữ nguyên lịch sử bài nộp cũ.

if (history) {
    history.innerHTML = items.length
        ? '<table><thead><tr>' +
          '<th>Bài</th><th>Kết quả</th><th>Điểm</th><th>Thời gian</th>' +
          '</tr></thead><tbody>' +
          items.map(x => `
            <tr>
                <td>
                    <a class="text-link"
                       href="/problems/${encodeURIComponent(x.problem_id ?? '')}">
                        ${escapeHtml(x.problem_id ?? '—')}
                    </a>
                </td>
                <td>${escapeHtml(x.verdict ?? '—')}</td>
                <td>${formatScore(x.score)}/${formatScore(x.max_score)}</td>
                <td>${escapeHtml(x.created_at ?? '—')}</td>
            </tr>
          `).join('') +
          '</tbody></table>'
        : 'Chưa có bài nộp.';
}

        })().catch(e => console.error('Lỗi tải tài khoản:', e)));
    }

    // Danh sách bài.
    if (problems || count || adminCount) {
        tasks.push(api('/api/problems').then(items => {
            if (problems) {
                problems.dataset.items = JSON.stringify(items);
                renderProblems(items);
            }

            if (count) count.textContent = items.length;

            if (adminCount) {
                adminCount.textContent =
                    `${items.length} bài đang được nạp từ ngân hàng dữ liệu.`;
            }
        }).catch(e => {
            console.error('Lỗi tải danh sách bài:', e);
            note(e.message);
        }));
    }

    // Bảng xếp hạng.
    if (rankings) {
        tasks.push(api('/api/leaderboard').then(rows => {
            rankings.innerHTML = rows.length
                ? '<table><thead><tr>' +
                  '<th>Hạng</th><th>Thành viên</th><th>Điểm</th><th>Bài có điểm</th>' +
                  '</tr></thead><tbody>' +
                  rows.map((x, i) => `
                    <tr>
                        <td>${i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : i + 1}</td>
                        <td>${escapeHtml(x.username)}</td>
                        <td><b>${formatScore(x.score)}</b></td>
                        <td>${formatScore(x.solved)}</td>
                    </tr>
                  `).join('') +
                  '</tbody></table>'
                : 'Chưa có thành tích. Hãy là người đầu tiên!';
        }).catch(e => console.error('Lỗi tải bảng xếp hạng:', e)));
    }

    await Promise.allSettled(tasks);
}

// ==================== TÌM KIẾM BÀI ====================

document.querySelector('#search')?.addEventListener('input', e => {
    const el = document.querySelector('#problems');
    if (!el) return;

    let items = [];

    try {
        items = JSON.parse(el.dataset.items || '[]');
    } catch {}

    const query = e.target.value.toLocaleLowerCase('vi');

    renderProblems(items.filter(p =>
        `${p.id} ${p.title} ${p.category} ${p.difficulty}`
            .toLocaleLowerCase('vi')
            .includes(query)
    ));
});

// ==================== ĐĂNG NHẬP / ĐĂNG KÝ ====================

for (const [id, path] of [
    ['login-form', '/api/login'],
    ['register-form', '/api/register']
]) {
    document.querySelector('#' + id)?.addEventListener('submit', async e => {
        e.preventDefault();

        const form = e.currentTarget;
        const button = form.querySelector('button');

        if (button) button.disabled = true;

        try {
            const data = await api(path, {
                method: 'POST',
                body: JSON.stringify(Object.fromEntries(new FormData(form)))
            });

            note(data.message || 'Thao tác thành công.');
            form.reset();

            await Promise.allSettled([refresh(), loadProfile()]);
        } catch (err) {
            note(err.message);
        } finally {
            if (button) button.disabled = false;
        }
    });
}

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

    button.disabled = true;
    result.textContent = 'Đang gửi bài...';

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

        result.textContent = 'Đã nhận bài. Đang chấm...';

        let finalResult = null;
        let delay = 500;
        let consecutiveErrors = 0;

        // Không giới hạn chờ 10 giây.
        // Tiếp tục hỏi máy chủ cho đến khi bài có kết quả cuối cùng.
        while (true) {
            await new Promise(resolve => setTimeout(resolve, delay));

            try {
                finalResult = await api(
                    `/api/submissions/${encodeURIComponent(data.submission_id)}/status`
                );

                consecutiveErrors = 0;
            } catch (err) {
                consecutiveErrors++;

                result.textContent =
                    `Đang chờ kết quả chấm bài... (lỗi kết nối ${consecutiveErrors})`;

                if (consecutiveErrors >= 5) {
                    throw err;
                }

                delay = Math.min(delay * 2, 5000);
                continue;
            }

            const verdict = finalResult.verdict;

            if (
                verdict &&
                verdict !== 'Queued' &&
                verdict !== 'Processing'
            ) {
                break;
            }

            result.textContent = 'Đang chấm bài...';
            delay = Math.min(Math.round(delay * 1.3), 2000);
        }

        // Hiện kết quả ngay tại khu vực nộp bài.
        result.textContent =
            `${finalResult.verdict}\n` +
            `Điểm: ${finalResult.score}/${finalResult.max_score}\n\n` +
            JSON.stringify(finalResult.details ?? {}, null, 2);

        // Cập nhật lịch sử và bảng xếp hạng.
        await refresh();

    } catch (err) {
        result.textContent =
            'Chưa lấy được kết quả chấm: ' + err.message +
            '\nBài nộp có thể vẫn đang được xử lý. Hãy thử tải lại sau.';
    } finally {
        button.disabled = false;
    }
});

// ==================== HỒ SƠ ====================

async function loadProfile() {
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
                <p><b>Tên đăng nhập:</b> ${escapeHtml(user.username)}</p>
                <p><b>Vai trò:</b> ${user.is_admin ? 'Quản trị viên' : 'Học sinh'}</p>
                <p><b>Trạng thái:</b> ${user.approved ? 'Đã duyệt' : 'Chờ duyệt'}</p>
                <p><b>Ngày tạo:</b> ${escapeHtml(user.created_at || '')}</p>
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
        if (avatar && color) avatar.style.background = color.value;

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
                            : `<button class="button button-primary approve-user"
                                       data-id="${escapeHtml(user.id)}">
                                   Duyệt tài khoản
                               </button>`
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

// ==================== KHỞI ĐỘNG ====================

Promise.allSettled([
    refresh(),
    loadProfile(),
    loadAdmin()
]);
