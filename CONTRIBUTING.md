# Contributing to SATL

Thank you for your interest in contributing to SATL - Secure Adaptive Transport Layer!

## Code of Conduct

- Be respectful and constructive
- Focus on technical merit
- Help others learn and improve

## How to Contribute

### Reporting Issues

- Use GitHub Issues for bug reports and feature requests
- Include clear reproduction steps
- Provide system information (OS, Python version)
- Attach relevant logs or error messages

### Submitting Changes

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/your-feature`
3. **Make your changes**
4. **Test thoroughly**: Run performance and endurance tests
5. **Commit with clear messages**: Follow the existing commit style
6. **Push to your fork**: `git push origin feature/your-feature`
7. **Open a Pull Request**: Describe your changes and motivation

### Code Style

- Follow PEP 8 for Python code
- Use type hints where appropriate
- Add docstrings for public functions
- Keep functions focused and small
- Comment complex logic

### Testing

Before submitting:

```bash
# Run performance test
python test_performance_bare.py

# Run smoke test (2 minutes)
python test_endurance_1h.py --duration 120

# Check metrics
curl http://localhost:10000/metrics
```

### Commit Messages

Format:
```
[Component] Brief description

Detailed explanation if needed.

Changes:
- Item 1
- Item 2
```

Examples:
```
[Core] Fix anti-replay window race condition

[Daemon] Add HTTP/2 support for forwarders

[Tests] Improve endurance test error reporting
```

### Security

- **DO NOT** commit secrets, keys, or credentials
- Report security vulnerabilities privately (not in public issues)
- Follow cryptographic best practices
- Document security implications of changes

### Performance

- Profile performance-critical changes
- Maintain P95 latency < 50ms @ 10 concurrent
- Avoid memory leaks (run endurance test)
- Document performance impact

### Documentation

Update documentation for:
- New features
- API changes
- Configuration options
- Performance characteristics

## Development Setup

```bash
# Clone repository
git clone https://github.com/Daniele-Cangi/SATL---Secure-Adaptive-Transport-Layer--.git
cd SATL---Secure-Adaptive-Transport-Layer--

# Install dependencies
pip install -r requirements.txt

# Start forwarders
.\profiles\switch_profile.ps1 perf

# Run tests
python test_performance_bare.py
```

## Areas for Contribution

### High Priority
- Production deployment automation
- Monitoring and alerting
- Load balancing between nodes
- IPv6 support

### Medium Priority
- Additional PQC algorithms
- Performance optimizations
- Documentation improvements
- Testing infrastructure

### Low Priority
- UI/dashboard for metrics
- Mobile client support
- Alternative backends (Redis, etc.)

## Questions?

- Open a GitHub Discussion for general questions
- Check existing Issues and PRs
- Read the documentation in `docs/`

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.

---

**Thank you for contributing to SATL!**
