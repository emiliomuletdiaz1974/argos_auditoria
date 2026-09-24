#!/usr/bin/env bash
# ARG-081 · CIS hardening of the appliance image (Ubuntu Server 24.04, Level 1 Server).
#
# Run by the image build after the base provisioning (ARG-002). Idempotent: a second run changes
# no file (content, mode or time), because every file is written only when its content differs and
# every line is added only when it is missing. Sections follow the numbering of the benchmark.
#
# What needs a real kernel (loading sysctl and the audit rules) or a package repository (auditd)
# is an error in an image build. Only with ARGOS_HARDEN_ALLOW_SKIP=1 (a container in the tests) is
# it skipped, and then with a "SKIP <section> - <why>" line, never in silence.
#
# Deviations from the benchmark are documented in hardening-exceptions.yaml (ip forwarding for
# k3s, removable media for the airlock) and read by tools/cis_gate.py.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALLOW_SKIP="${ARGOS_HARDEN_ALLOW_SKIP:-0}"

changed() { echo "changed $1"; }

skip_or_fail() {  # skip_or_fail SECTION REASON
  if [ "$ALLOW_SKIP" = "1" ]; then
    echo "SKIP $1 - $2"
  else
    echo "ERROR $1 - $2 (set ARGOS_HARDEN_ALLOW_SKIP=1 only outside an image build)" >&2
    exit 1
  fi
}

put() {  # put DEST MODE < content: write only when the content differs
  local dest="$1" mode="$2" tmp
  tmp="$(mktemp)"
  cat > "$tmp"
  if [ -f "$dest" ] && cmp -s "$tmp" "$dest"; then
    rm -f "$tmp"
  else
    mkdir -p "$(dirname "$dest")"
    install -m "$mode" "$tmp" "$dest"
    rm -f "$tmp"
    changed "$dest"
  fi
  if [ "$(stat -c %a "$dest")" != "$mode" ]; then
    chmod "$mode" "$dest"
    changed "$dest (mode)"
  fi
}

ensure_line() {  # ensure_line FILE LINE: the exact line, once
  local file="$1" line="$2"
  [ -e "$file" ] || : > "$file"  # never touch: the time of the file must not move
  if ! grep -qxF -- "$line" "$file"; then
    printf '%s\n' "$line" >> "$file"
    changed "$file"
  fi
}

set_key() {  # set_key FILE KEY VALUE: "KEY<TAB>VALUE", replacing the key if it is there
  local file="$1" key="$2" value="$3"
  [ -f "$file" ] || return 0
  if grep -qxF -- "$(printf '%s\t%s' "$key" "$value")" "$file"; then
    return 0
  fi
  if grep -qE "^[#[:space:]]*${key}[[:space:]]" "$file"; then
    sed -i -E "s|^[#[:space:]]*${key}[[:space:]].*|$(printf '%s\t%s' "$key" "$value")|" "$file"
  else
    printf '%s\t%s\n' "$key" "$value" >> "$file"
  fi
  changed "$file ($key)"
}

### 1.1.1 Filesystem kernel modules nobody needs on the appliance.
# Not usb-storage: the airlock (ARG-090) works with removable media (exception 1.1.1.10).
for module in cramfs freevxfs hfs hfsplus jffs2 udf; do
  put "/etc/modprobe.d/argos-${module}.conf" 644 <<EOF
install ${module} /bin/false
blacklist ${module}
EOF
done

### 1.1.2 Temporary filesystems with restrictive options.
ensure_line /etc/fstab "tmpfs /dev/shm tmpfs defaults,nodev,nosuid,noexec 0 0"
ensure_line /etc/fstab "tmpfs /tmp tmpfs defaults,nodev,nosuid,noexec,mode=1777 0 0"

### 1.5 Process hardening: no core dumps of setuid programs.
put /etc/security/limits.d/60-argos-core.conf 644 <<'EOF'
* hard core 0
EOF

### 3.3 Network and kernel parameters.
put /etc/sysctl.d/60-argos-hardening.conf 644 <<'EOF'
# ARG-081 · kernel and network parameters (CIS 1.5, 3.3). Loaded at boot by systemd-sysctl.
# 3.3.1: k3s routes the traffic of the pods; documented exception in hardening-exceptions.yaml.
net.ipv4.ip_forward=1
net.ipv4.conf.all.send_redirects=0
net.ipv4.conf.default.send_redirects=0
net.ipv4.conf.all.accept_redirects=0
net.ipv4.conf.default.accept_redirects=0
net.ipv4.conf.all.secure_redirects=0
net.ipv4.conf.default.secure_redirects=0
net.ipv4.conf.all.accept_source_route=0
net.ipv4.conf.default.accept_source_route=0
net.ipv4.conf.all.log_martians=1
net.ipv4.conf.default.log_martians=1
net.ipv4.conf.all.rp_filter=1
net.ipv4.conf.default.rp_filter=1
net.ipv4.icmp_echo_ignore_broadcasts=1
net.ipv4.icmp_ignore_bogus_error_responses=1
net.ipv4.tcp_syncookies=1
net.ipv6.conf.all.accept_ra=0
net.ipv6.conf.default.accept_ra=0
net.ipv6.conf.all.accept_redirects=0
net.ipv6.conf.default.accept_redirects=0
kernel.randomize_va_space=2
kernel.kptr_restrict=2
kernel.dmesg_restrict=1
kernel.yama.ptrace_scope=1
fs.suid_dumpable=0
fs.protected_hardlinks=1
fs.protected_symlinks=1
EOF
if [ -w /proc/sys/kernel/randomize_va_space ]; then
  sysctl -q --system
else
  skip_or_fail "3.3 sysctl" "the kernel parameters are not writable here (a container); they load at boot"
fi

### 4.1 auditd: what matters, not everything. The rules are versioned in audit/argos.rules.
if ! dpkg-query -W -f='${Status}' auditd 2>/dev/null | grep -q "install ok installed"; then
  if DEBIAN_FRONTEND=noninteractive apt-get install -y -qq auditd audispd-plugins >/dev/null 2>&1; then
    changed "auditd (installed)"
  else
    skip_or_fail "4.1 auditd package" "auditd is not installed and no repository is reachable"
  fi
fi
put /etc/audit/rules.d/argos.rules 640 < "$HERE/audit/argos.rules"
if command -v augenrules >/dev/null 2>&1 && auditctl -s >/dev/null 2>&1; then
  augenrules --load >/dev/null
else
  skip_or_fail "4.1 audit rules" "no running audit subsystem here; the rules load at boot"
fi

### 5.1 SSH: key and the bastion of the client, nothing else.
put /etc/ssh/sshd_config.d/60-argos.conf 600 <<'EOF'
# ARG-081 · SSH of the appliance (CIS 5.1): key only, through the bastion of the client.
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
HostbasedAuthentication no
IgnoreRhosts yes
X11Forwarding no
AllowTcpForwarding no
AllowGroups argos-ops
MaxAuthTries 3
MaxSessions 4
LoginGraceTime 60
ClientAliveInterval 300
ClientAliveCountMax 2
LogLevel VERBOSE
Banner /etc/issue.net
EOF

### 1.7 Warning banners.
for banner in /etc/issue /etc/issue.net; do
  put "$banner" 644 <<'EOF'
Authorised access only. Every action on this appliance is recorded.
EOF
done

### 5.4 Password policy of local accounts (the people use Keycloak; these are operators).
set_key /etc/login.defs PASS_MAX_DAYS 365
set_key /etc/login.defs PASS_MIN_DAYS 1
set_key /etc/login.defs PASS_WARN_AGE 7
set_key /etc/login.defs UMASK 027

### 2.x Packages the appliance does not use: removed only if they are there.
for package in telnet rsh-client talk avahi-daemon cups isc-dhcp-server rpcbind nfs-kernel-server; do
  if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "install ok installed"; then
    DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq "$package" >/dev/null
    changed "$package (purged)"
  fi
done

echo "hardening applied; the CIS scanner validates the image (tools/cis_gate.py)"
