# -*- mode: ruby -*-
# vi: set ft=ruby :

VERSION = "2" # Vagrantfile API/syntax version. Don't touch unless you know what you're doing!
BOX = "ubuntu/trusty64"
BOX_URL = "https://atlas.hashicorp.com/ubuntu/boxes/trusty64/versions/20160714.0.0/providers/virtualbox.box"
PORT = 8000


Vagrant.configure(VERSION) do |config|
  config.vm.box = BOX
  config.vm.box_url = BOX_URL
  config.vm.network :private_network, type: :dhcp
  config.vm.network :forwarded_port, guest: PORT, host: PORT, auto_correct: true
  config.vm.synced_folder ".", "/home/vagrant/muckrock/"
  
  host = RbConfig::CONFIG['host_os']
  # Give VM access to all cpu cores on the host
  if host =~ /darwin/
    cpus = `sysctl -n hw.physicalcpu`.to_i
  elsif host =~ /linux/
    cpus = `nproc`.to_i
  else # sorry Windows folks, I can't help you
    cpus = 1
  end

  config.vm.provider "virtualbox" do |v|
    v.customize ["modifyvm", :id, "--ioapic", "on"]
    v.customize ["modifyvm", :id, "--cpuexecutioncap", "90"]
    v.customize ["modifyvm", :id, "--cpus", cpus]
    v.customize ["modifyvm", :id, "--memory", 2048]
  end

  # remove clashing versions supplied by trusty
  config.vm.provision :shell, :inline => "sudo apt-get -y remove python"

  # provision with puppet
  config.vm.provision :puppet do |puppet|
    puppet.manifests_path = "puppet/manifests"
    puppet.manifest_file = "default.pp"
    puppet.module_path = "puppet/manifests/modules"
  end

end
