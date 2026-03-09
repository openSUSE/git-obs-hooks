#
# spec file for package git-obs-hooks
#
# Copyright (c) 2026 SUSE LLC
#
# All modifications and additions to the file contributed by third parties
# remain the property of their copyright owners, unless otherwise agreed
# upon. The license for this file, and modifications and additions to the
# file, is the same license as for the pristine package itself (unless the
# license for the pristine package is not an Open Source License, in which
# case the license is the MIT License). An "Open Source License" is a
# license that conforms to the Open Source Definition (Version 1.9)
# published by the Open Source Initiative.

# Please submit bugfixes or comments via https://bugs.opensuse.org/
#


Name:           git-obs-hooks
Version:        1.0
Release:        0
Summary:        Client-side hooks for git and git-based osc
License:        GPL-2.0-or-later
Group:          Development/Tools/Other
URL:            https://github.com/openSUSE/git-obs-hooks
Source0:        https://github.com/openSUSE/git-obs-hooks/archive/refs/tags/%{version}.tar.gz#/%{name}-%{version}.tar.gz
Requires:       %{name}-common >= %{version}
BuildArch:      noarch

%description
Client-side hooks for git and git-based osc.

%package common
Summary:        Git hooks for the OBS and Gitea ecosystem
Group:          Development/Tools/Other
Requires:       git-core
Requires:       git-lfs
BuildArch:      noarch

%description common
Manage and run git hooks in the Open Build Service (OBS) ecosystem,
for both client-side (git, osc) and server-side (Gitea) operations.

%package gitea
Summary:        Server-side git hooks for Gitea
Group:          Development/Tools/Other
Requires:       %{name} >= %{version}
BuildArch:      noarch

%description gitea
Server-side hooks for Gitea - based on Gitea's generated hooks.

%prep
%autosetup

%build

%install
install -d %{buildroot}%{_libexecdir}/%{name}
install -m 755 src/*install %{buildroot}%{_libexecdir}/%{name}/
cp -rv src/{all-hooks,gitea,git-obs,common} %{buildroot}%{_libexecdir}/%{name}/

%files
%dir %{_libexecdir}/git-obs-hooks/git-obs
%{_libexecdir}/git-obs-hooks/git-obs/*
%{_libexecdir}/git-obs-hooks/git-obs-hooks-install
%{_libexecdir}/git-obs-hooks/git-obs-hooks-uninstall

%files gitea
%dir %{_libexecdir}/git-obs-hooks/gitea
%{_libexecdir}/git-obs-hooks/gitea/*
%{_libexecdir}/git-obs-hooks/gitea-hooks-install
%{_libexecdir}/git-obs-hooks/gitea-hooks-uninstall

%files common
%doc README.md
%license LICENSE
%dir %{_libexecdir}/git-obs-hooks/
%{_libexecdir}/git-obs-hooks/common
%dir %{_libexecdir}/git-obs-hooks/all-hooks/
%{_libexecdir}/git-obs-hooks/all-hooks/*

%changelog
