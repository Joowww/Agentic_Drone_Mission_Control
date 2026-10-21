#ifndef TFG_ROVER_PRIVATE_JOURNAL_HPP
#define TFG_ROVER_PRIVATE_JOURNAL_HPP
#include <cerrno>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace tfg::rover_passive {
class PrivateJournal {
public:
  explicit PrivateJournal(const std::string & path) {
    const std::filesystem::path output(path);
    if (!output.is_absolute() || output.filename().empty()) throw std::invalid_argument("Absolute output file required");
    int parent = ::open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (parent < 0) throw std::runtime_error("Cannot open output root");
    try {
      for (const auto & part : output.parent_path().relative_path()) {
        if (part == "." || part == "..") throw std::invalid_argument("No relative path components");
        int child = ::openat(parent, part.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        if (child < 0) throw std::runtime_error("Output directory missing or symlinked");
        ::close(parent);
        parent = child;
      }
      struct stat info{};
      if (::fstat(parent, &info) || info.st_uid != ::geteuid() || (info.st_mode & 0077))
        throw std::runtime_error("Output parent must be owned and private (0700)");
      fd_ = ::openat(parent, output.filename().c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
      if (fd_ < 0) throw std::runtime_error("Cannot exclusively create private output");
      parent_ = parent;
    } catch (...) { ::close(parent); throw; }
  }
  PrivateJournal(const PrivateJournal &) = delete;
  PrivateJournal & operator=(const PrivateJournal &) = delete;
  ~PrivateJournal() { if (fd_ >= 0) ::close(fd_); if (parent_ >= 0) ::close(parent_); }
  void append(const std::string & json) {
    if (fd_ < 0) throw std::runtime_error("Journal closed");
    const auto line = json + '\n';
    std::size_t offset = 0;
    while (offset < line.size()) {
      const auto written = ::write(fd_, line.data()+offset, line.size()-offset);
      if (written <= 0) throw std::runtime_error("Journal write uncertain");
      offset += static_cast<std::size_t>(written);
    }
    if (::fsync(fd_) || ::fsync(parent_)) throw std::runtime_error("Journal fsync uncertain");
  }
  void finish() {
    if (fd_ < 0) throw std::runtime_error("Journal already closed");
    if (::fsync(fd_)) throw std::runtime_error("Journal final fsync uncertain");
    int closing = fd_; fd_ = -1;
    if (::close(closing)) throw std::runtime_error("Journal close uncertain");
    if (::fsync(parent_)) throw std::runtime_error("Output directory fsync uncertain");
  }
private:
  int fd_ = -1, parent_ = -1;
};
}  // namespace tfg::rover_passive
#endif
