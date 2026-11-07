"""Automated Playwright UI test suite verifying:
1. Registration (Sign-up) flow, validations, password toggles.
2. Email verification flow and resend code.
3. Forgot password flow.
4. Reset password flow.
5. Navigation state switching (logged out vs logged in).
6. Minimalist UI criteria: no slogans, no emojis, no Rule IDs on main UI, 6 accordion groups, 40 threshold fields, responsive layout.
"""
import os, pathlib, subprocess, sys, time, urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = pathlib.Path(__file__).resolve().parents[1]
PORT = 8785

def run_tests():
    server = subprocess.Popen([sys.executable, str(ROOT / 'demo.py'), '--port', str(PORT)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        for _ in range(50):
            try:
                opener.open(f'http://127.0.0.1:{PORT}/config.json', timeout=0.2)
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError('Demo server failed to start')

        with sync_playwright() as p:
            kwargs = {'headless': True, 'args': ['--no-sandbox', '--disable-dev-shm-usage']}
            if os.environ.get('CHROMIUM_EXECUTABLE'):
                kwargs['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
            browser = p.chromium.launch(**kwargs)
            context = browser.new_context(viewport={'width': 1280, 'height': 800})
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))

            page.goto(f'http://127.0.0.1:{PORT}/')

            # 1. Check Initial Logged-out State & Navigation
            expect(page.locator('#nav-guest')).to_be_visible()
            expect(page.locator('#nav-auth')).to_be_hidden()
            expect(page.locator('#view-login')).to_be_visible()
            expect(page.locator('#view-register')).to_be_hidden()
            expect(page.locator('#login')).to_have_text('Đăng nhập')
            expect(page.locator('#breadcrumb')).to_have_text('Đăng nhập')

            # Verify no slogans in logged-out page
            body_text = page.locator('body').inner_text()
            for forbidden in [
                'Quyền đọc. Quyền chủ động.',
                'Guardian đưa ra bằng chứng',
                'Tập trung vào tài nguyên cần bạn kiểm tra',
                'Mỗi cảnh báo đi kèm lý do'
            ]:
                assert forbidden not in body_text, f'Forbidden slogan found: {forbidden}'

            # 2. Test Switch to Registration View
            page.locator('#nav-register').click()
            expect(page.locator('#view-register')).to_be_visible()
            expect(page.locator('#view-login')).to_be_hidden()
            expect(page.locator('#breadcrumb')).to_have_text('Đăng ký')

            # Test Password Toggle
            pw_input = page.locator('#reg-password')
            pw_toggle = page.locator('.btn-toggle-pw[data-for="reg-password"]')
            expect(pw_input).to_have_attribute('type', 'password')
            expect(pw_toggle).to_have_text('Hiện')
            pw_toggle.click()
            expect(pw_input).to_have_attribute('type', 'text')
            expect(pw_toggle).to_have_text('Ẩn')
            pw_toggle.click()
            expect(pw_input).to_have_attribute('type', 'password')

            # 3. Test Registration Validations
            # 3a. Invalid Email
            page.locator('#reg-email').fill('invalid-email')
            page.locator('#reg-password').fill('Short1!')
            page.locator('#reg-confirm').fill('Short1!')
            page.locator('#reg-submit').click()
            expect(page.locator('#reg-feedback')).to_contain_text('Định dạng email không hợp lệ')

            # 3b. Password Policy: too short (< 12 chars)
            page.locator('#reg-email').fill('newuser@example.com')
            page.locator('#reg-password').fill('Short1!Aa')
            page.locator('#reg-confirm').fill('Short1!Aa')
            page.locator('#reg-submit').click()
            expect(page.locator('#reg-feedback')).to_contain_text('ít nhất 12 ký tự')

            # 3c. Password Policy: no uppercase
            page.locator('#reg-password').fill('lowercase123456!@#')
            page.locator('#reg-confirm').fill('lowercase123456!@#')
            page.locator('#reg-submit').click()
            expect(page.locator('#reg-feedback')).to_contain_text('chữ hoa')

            # 3d. Password Policy: no lowercase
            page.locator('#reg-password').fill('UPPERCASE123456!@#')
            page.locator('#reg-confirm').fill('UPPERCASE123456!@#')
            page.locator('#reg-submit').click()
            expect(page.locator('#reg-feedback')).to_contain_text('chữ thường')

            # 3e. Password Policy: no number
            page.locator('#reg-password').fill('PasswordWithoutNum!@#')
            page.locator('#reg-confirm').fill('PasswordWithoutNum!@#')
            page.locator('#reg-submit').click()
            expect(page.locator('#reg-feedback')).to_contain_text('chữ số')

            # 3f. Password Policy: no special char
            page.locator('#reg-password').fill('PasswordWithoutSpecial123')
            page.locator('#reg-confirm').fill('PasswordWithoutSpecial123')
            page.locator('#reg-submit').click()
            expect(page.locator('#reg-feedback')).to_contain_text('ký tự đặc biệt')

            # 3g. Passwords do not match
            page.locator('#reg-password').fill('ValidPass12345!@#')
            page.locator('#reg-confirm').fill('DifferentPass12345!@#')
            page.locator('#reg-submit').click()
            expect(page.locator('#reg-feedback')).to_contain_text('không khớp')

            # 3h. Successful Registration -> Transitions to Verify view
            page.locator('#reg-password').fill('ValidPass12345!@#')
            page.locator('#reg-confirm').fill('ValidPass12345!@#')
            page.locator('#reg-submit').click()
            expect(page.locator('#view-verify')).to_be_visible()
            expect(page.locator('#verify-email')).to_have_value('newuser@example.com')
            expect(page.locator('#status')).to_contain_text('Đăng ký thành công')

            # Passwords must be cleared from DOM for security
            expect(page.locator('#reg-password')).to_have_value('')
            expect(page.locator('#reg-confirm')).to_have_value('')

            # 4. Test Email Verification View
            # 4a. Resend code
            page.locator('#verify-resend').click()
            expect(page.locator('#status')).to_contain_text('Đã gửi lại mã xác minh')

            # 4b. Invalid code
            page.locator('#verify-code').fill('000000')
            page.locator('#verify-submit').click()
            expect(page.locator('#status')).to_contain_text('Mã xác minh không chính xác')

            # 4c. Valid verification code -> Transitions to Login
            page.locator('#verify-code').fill('123456')
            page.locator('#verify-submit').click()
            expect(page.locator('#view-login')).to_be_visible()
            expect(page.locator('#status')).to_contain_text('Xác minh tài khoản thành công')

            # 5. Test Forgot Password Flow
            page.locator('#nav-forgot').click()
            expect(page.locator('#view-forgot')).to_be_visible()
            expect(page.locator('#breadcrumb')).to_have_text('Quên mật khẩu')

            # 5a. Invalid email
            page.locator('#forgot-email').fill('bademail')
            page.locator('#forgot-submit').click()
            expect(page.locator('#forgot-feedback')).to_contain_text('Định dạng email không hợp lệ')

            # 5b. Valid request -> Transitions to Reset view
            page.locator('#forgot-email').fill('newuser@example.com')
            page.locator('#forgot-submit').click()
            expect(page.locator('#view-reset')).to_be_visible()
            expect(page.locator('#reset-email')).to_have_value('newuser@example.com')
            expect(page.locator('#status')).to_contain_text('Mã đặt lại mật khẩu đã được gửi')

            # 6. Test Reset Password Validations
            page.locator('#reset-code').fill('123456')
            page.locator('#reset-password').fill('Short1!')
            page.locator('#reset-confirm').fill('Short1!')
            page.locator('#reset-submit').click()
            expect(page.locator('#reset-feedback')).to_contain_text('ít nhất 12 ký tự')

            # Passwords mismatch
            page.locator('#reset-password').fill('NewValidPassword123!@#')
            page.locator('#reset-confirm').fill('MismatchPassword123!@#')
            page.locator('#reset-submit').click()
            expect(page.locator('#reset-feedback')).to_contain_text('không khớp')

            # Successful reset -> Transitions to Login
            page.locator('#reset-password').fill('NewValidPassword123!@#')
            page.locator('#reset-confirm').fill('NewValidPassword123!@#')
            page.locator('#reset-submit').click()
            expect(page.locator('#view-login')).to_be_visible()
            expect(page.locator('#status')).to_contain_text('Đặt lại mật khẩu thành công')

            # 7. Test Log In & Auth Navigation
            page.locator('#start').click()
            expect(page.locator('#app')).to_be_visible()
            expect(page.locator('#welcome')).to_be_hidden()
            expect(page.locator('#nav-auth')).to_be_visible()
            expect(page.locator('#nav-guest')).to_be_hidden()
            expect(page.locator('#login')).to_have_text('Đăng xuất')

            # Verify navigation items
            nav_auth_buttons = [b.inner_text().strip() for b in page.locator('#nav-auth button').all()]
            assert any('Tổng quan' in b for b in nav_auth_buttons), nav_auth_buttons
            assert any('Tài nguyên cần kiểm tra' in b for b in nav_auth_buttons), nav_auth_buttons
            assert any('Lịch sử quét' in b for b in nav_auth_buttons), nav_auth_buttons
            assert any('Kết nối AWS' in b for b in nav_auth_buttons), nav_auth_buttons
            assert any('Cấu hình' in b for b in nav_auth_buttons), nav_auth_buttons
            assert any('Đăng xuất' in b for b in nav_auth_buttons), nav_auth_buttons

            # 8. Test Settings Page: 6 Accordions, 40 Fields, No Emojis, No Rule IDs
            page.locator('#nav-auth [data-page="settings"]').click()
            expect(page.locator('details.settings-group')).to_have_count(6)

            # Check that summary titles have NO emojis
            summary_texts = [s.inner_text() for s in page.locator('details.settings-group summary').all()]
            for text in summary_texts:
                assert not any(ord(c) > 0x2000 and ord(c) not in range(0x2010, 0x2213) for c in text), f'Emoji found in summary: {text}'

            # Check that Rule IDs are NOT displayed on main settings cards
            settings_text = page.locator('#settings-groups').inner_text()
            for rule_id in [
                'EC2_LOW_UTILIZATION', 'LAMBDA_UNUSED', 'EBS_UNATTACHED',
                'SNAPSHOT_OLD_UNREFERENCED', 'NAT_LOW_UTILIZATION', 'ALB_LOW_UTILIZATION'
            ]:
                assert rule_id not in settings_text, f'Rule ID {rule_id} should not be visible on main settings UI'

            # Verify all 40 threshold input fields exist
            all_40_fields = [
                'cpu_percent', 'network_mib_hour', 'window_hours', 'interval_hours',
                'lambda_unused_days', 'lambda_max_invocations', 'asg_zero_days', 'ecs_empty_days', 'eks_idle_days',
                'orphan_hours', 'snapshot_days', 'rds_snapshot_days', 'efs_no_mount_days', 'ecr_image_days', 'fsx_idle_days', 'backup_point_days',
                'rds_cpu_percent', 'rds_connections', 'dynamodb_idle_days', 'elasticache_idle_days', 'memorydb_idle_days', 'documentdb_idle_days', 'neptune_idle_days',
                'nat_mib_hour', 'alb_requests_hour', 'nlb_new_flows_hour', 'sg_unused_days', 'vpc_endpoint_unused_days', 'cloudfront_requests_day',
                'sagemaker_idle_days', 'opensearch_idle_days', 'redshift_idle_days', 'msk_idle_days', 'kinesis_idle_days',
                'log_group_retention_days', 'sqs_idle_days', 'sns_unused_days', 'eventbridge_unused_days', 'stepfunctions_unused_days', 'apigateway_unused_days'
            ]
            for fid in all_40_fields:
                expect(page.locator(f'#{fid}')).to_have_count(1)

            # Verify no permanent repeated help text under inputs
            assert page.locator('.field-help').count() == 0, 'Permanent field help lines should be removed'

            # 9. Test Mobile Viewport & Responsiveness
            mobile_ctx = browser.new_context(viewport={'width': 375, 'height': 812}, is_mobile=True)
            mp = mobile_ctx.new_page()
            mp.goto(f'http://127.0.0.1:{PORT}/')
            assert mp.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile horizontal overflow detected'
            mp.locator('#start').click()
            expect(mp.locator('#app')).to_be_visible()
            assert mp.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Authenticated mobile overflow detected'

            # 10. Test Logout
            page.locator('#nav-logout').click()
            expect(page.locator('#app')).to_be_hidden()
            expect(page.locator('#welcome')).to_be_visible()
            expect(page.locator('#nav-guest')).to_be_visible()
            expect(page.locator('#nav-auth')).to_be_hidden()

            assert not errors, f'Unexpected page errors: {errors}'
            browser.close()
            print('ALL AUTH & MINIMALIST UI TESTS PASS!')
    finally:
        server.terminate()
        server.wait(timeout=5)

if __name__ == '__main__':
    run_tests()
