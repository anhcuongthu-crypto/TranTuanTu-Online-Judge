
async function api(url, opts = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...(opts.headers || {})
    };

    const r = await fetch(url, {
        credentials: 'same-origin',
        ...opts,
        headers
    });

    let d = {};

    try {
        d = await r.json();
    } catch {}

    if (!r.ok) {
        throw Error(d.error || `HTTP ${r.status}`);
    }

    return d;
}

function note(s) {
    const e = document.querySelector('#notice');
    if (e) e.textContent = s;
}

function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[c]));
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
                ${p.total_score} điểm
            </small>
        </a>
    `).join('') || '<div class="glass-card">Không tìm thấy bài phù hợp.</div>';
}

async function refresh() {
    try {
        const me = await api('/api/me');
        const u = me.user;
const authSection = document.querySelector('#auth-section');
if (authSection) {
    authSection.style.display = u ? 'none' : 'grid';
}
        const status = document.querySelector('#user-status');
        if (status) {
            status.textContent = u
                ? `Xin chào, ${u.username}`
                : 'Chưa đăng nhập';
        }

        const logout = document.querySelector('#logout-button');
        if (logout) logout.hidden = !u;

        const admin = document.querySelector('#admin-link');
        if (admin) admin.hidden = !(u && u.is_admin);

        if (u) {
            const h = await api('/api/submissions');
            const el = document.querySelector('#history');

            if (el) {
                el.innerHTML = h.length
                    ? '<table><tr><th>Bài</th><th>Kết quả</th><th>Điểm</th><th>Thời gian</th></tr>' +
                      h.map(x => `
                        <tr>
                            <td>
                                <a class="text-link"
                                   href="/problems/${encodeURIComponent(x.problem_id)}">
                                    ${escapeHtml(x.problem_id)}
                                </a>
                            </td>
                            <td>${escapeHtml(x.verdict)}</td>
                            <td>${x.score}/${x.max_score}</td>
                            <td>${escapeHtml(x.created_at)}</td>
                        </tr>
                      `).join('') +
                      '</table>'
                    : 'Chưa có bài nộp.';
            }
        }
    } catch (e) {
        console.error('Lỗi tải thông tin tài khoản:', e);
    }

    try {
        const p = await api('/api/problems');
        const el = document.querySelector('#problems');

        if (el) {
            el.dataset.items = JSON.stringify(p);
            renderProblems(p);
        }

        const count = document.querySelector('#problem-count');
        if (count) count.textContent = p.length;

        const ac = document.querySelector('#admin-problem-count');
        if (ac) {
            ac.textContent = `${p.length} bài đang được nạp từ ngân hàng dữ liệu.`;
        }
    } catch (e) {
        note(e.message);
    }

    try {
        const rows = await api('/api/leaderboard');
        const el = document.querySelector('#rankings');

        if (el) {
            el.innerHTML = rows.length
                ? '<table><thead><tr><th>Hạng</th><th>Thành viên</th><th>Điểm</th><th>Bài có điểm</th></tr></thead><tbody>' +
                  rows.map((x, i) => `
                    <tr>
                        <td>${i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : i + 1}</td>
                        <td>${escapeHtml(x.username)}</td>
                        <td><b>${x.score}</b></td>
                        <td>${x.solved}</td>
                    </tr>
                  `).join('') +
                  '</tbody></table>'
                : 'Chưa có thành tích. Hãy là người đầu tiên!';
        }
    } catch (e) {
        console.error('Lỗi tải bảng xếp hạng:', e);
    }
}

document.querySelector('#search')?.addEventListener('input', e => {
    const el = document.querySelector('#problems');
    let items = [];

    try {
        items = JSON.parse(el.dataset.items || '[]');
    } catch {}

    const q = e.target.value.toLocaleLowerCase('vi');

    renderProblems(items.filter(p =>
        (
            p.id + ' ' + p.title + ' ' +
            p.category + ' ' + p.difficulty
        ).toLocaleLowerCase('vi').includes(q)
    ));
});

for (const [id, path] of [
    ['login-form', '/api/login'],
    ['register-form', '/api/register']
]) {
    document.querySelector('#' + id)?.addEventListener('submit', async e => {
        e.preventDefault();

        const f = e.currentTarget;
        const b = f.querySelector('button');

        if (b) b.disabled = true;

        try {
            const d = await api(path, {
                method: 'POST',
                body: JSON.stringify(
                    Object.fromEntries(new FormData(f))
                )
            });

            note(d.message || 'Thao tác thành công.');
            f.reset();
            await refresh();
        } catch (err) {
            note(err.message);
        } finally {
            if (b) b.disabled = false;
        }
    });
}

document.querySelector('#logout-button')?.addEventListener('click', async () => {
    try {
        await api('/api/logout', { method: 'POST' });
        location.href = '/';
    } catch (e) {
        note(e.message);
    }
});

document.querySelector('#submit')?.addEventListener('click', async e => {
    const b = e.currentTarget;
    const result = document.querySelector('#result');

    if (!result) {
        note('Không tìm thấy vùng hiển thị kết quả.');
        return;
    }

    b.disabled = true;
    result.textContent = 'Đang gửi bài...';

    try {
        const d = await api('/api/submit', {
            method: 'POST',
            body: JSON.stringify({
                problem_id: b.dataset.problem,
                source_code: document.querySelector('#source').value,
                language_id: document.querySelector('#language').value
            })
        });

        result.textContent = 'Đã nhận bài. Đang chấm...';

        let finalResult = null;

        while (true) {
            await new Promise(resolve => setTimeout(resolve, 1500));

            finalResult = await api(
                `/api/submissions/${d.submission_id}/status`
            );

            if (
                finalResult.verdict !== 'Queued' &&
                finalResult.verdict !== 'Processing'
            ) {
                break;
            }

            result.textContent = 'Đang chấm bài...';
        }

        result.textContent =
            `${finalResult.verdict}\n` +
            `Điểm: ${finalResult.score}/${finalResult.max_score}\n\n` +
            JSON.stringify(finalResult.details, null, 2);

        await refresh();
    } catch (err) {
        result.textContent = 'Không chấm được: ' + err.message;
    } finally {
        b.disabled = false;
    }
});

async function loadProfile() {
    const form = document.querySelector('#profile-form');
    if (!form) return;

    try {
        const d = await api('/api/me');
        const u = d.user;

        if (!u) {
            document.querySelector('#profile-details').textContent =
                'Vui lòng đăng nhập trước.';
            form.querySelector('button').disabled = true;
            return;
        }

        form.bio.value = u.bio || '';
        form.avatar_color.value = u.avatar_color || '#7c3aed';

        const avatar = document.querySelector('#profile-avatar');

        avatar.textContent = u.username.slice(0, 2).toUpperCase();
        avatar.style.background = form.avatar_color.value;

        document.querySelector('#profile-details').innerHTML = `
            <p><b>Tên đăng nhập:</b> ${escapeHtml(u.username)}</p>
            <p><b>Vai trò:</b> ${u.is_admin ? 'Quản trị viên' : 'Học sinh'}</p>
            <p><b>Trạng thái:</b> ${u.approved ? 'Đã duyệt' : 'Chờ duyệt'}</p>
            <p><b>Ngày tạo:</b> ${escapeHtml(u.created_at || '')}</p>
        `;
    } catch (e) {
        document.querySelector('#profile-details').textContent = e.message;
    }
}

document.querySelector('#profile-form')?.addEventListener('submit', async e => {
    e.preventDefault();

    const f = e.currentTarget;
    const out = document.querySelector('#profile-notice');

    try {
        await api('/api/profile', {
            method: 'PUT',
            body: JSON.stringify({
                bio: f.bio.value,
                avatar_color: f.avatar_color.value
            })
        });

        out.textContent = 'Đã lưu hồ sơ.';
        document.querySelector('#profile-avatar').style.background =
            f.avatar_color.value;

        await loadProfile();
    } catch (err) {
        out.textContent = err.message;
    }
});

document.querySelector('#avatar_color')?.addEventListener('input', e => {
    const avatar = document.querySelector('#profile-avatar');
    if (avatar) avatar.style.background = e.target.value;
});

async function loadAdmin() {
    const el = document.querySelector('#admin-users');
    if (!el) return;

    try {
        const users = await api('/api/admin/users');

        el.innerHTML = users.length
            ? users.map(u => `
                <div class="admin-user">
                    <div>
                        <b>${escapeHtml(u.username)}</b>
                        <small>
                            ${u.approved ? 'Đã duyệt' : 'Đang chờ duyệt'}
                            · ${escapeHtml(u.created_at)}
                        </small>
                    </div>
                    ${
                        u.approved
                            ? '<span class="pill pill-green">Đã duyệt</span>'
                            : `<button class="button button-primary approve-user"
                                       data-id="${u.id}">Duyệt tài khoản</button>`
                    }
                </div>
            `).join('')
            : 'Không có yêu cầu tài khoản.';

        el.querySelectorAll('.approve-user').forEach(b => {
            b.addEventListener('click', async () => {
                b.disabled = true;

                try {
                    await api(
                        `/api/admin/users/${b.dataset.id}/approve`,
                        { method: 'POST' }
                    );

                    await loadAdmin();
                } catch (e) {
                    alert(e.message);
                    b.disabled = false;
                }
            });
        });
    } catch (e) {
        el.textContent = e.message;
    }
}

document.querySelector('#reload-users')?.addEventListener('click', loadAdmin);

refresh();
loadProfile();
loadAdmin();
