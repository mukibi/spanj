#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;
use Storable qw/freeze thaw/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir,$modem_manager1);

my %session;
my %auth_params;

my $logd_in = 0;
my $authd = 0;

my $con;

#used by view inbox/sent messages
#i really should take that advice about simple programs
#connected by clean interfaces.
my $page = 1;
my $per_page = 10;

my %grading;

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		my $id = $session{"id"};
		if ($id eq "1") {
			$authd++;
		}
	}
	#per page set
	if (exists $session{"per_page"} and $session{"per_page"} =~ /^(\d+)$/) {
		$per_page = $1;
	}
}

my $content = '';
my $feedback = '';
my $js = '';
my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/message.cgi">Send Messages</a>
	<hr> 
};

unless ($authd) {

	if ($logd_in) {
		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Send Messages</title>
</head>
<body>
$header
<p><span style="color: red">Sorry, you do not have the appropriate privileges to send messages.</span> Only the administrator is authorized to take this action.
</body>
</html> 
*;

		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}

	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/message.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Yans: Send Messages</title>
</head>
<body>
You should have been redirected to <a href="/login.html?cont=/cgi-bin/message.cgi">/login.html?cont=/cgi-bin/message.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/message.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

my $post_mode = 0;
my $boundary = undef;
my $multi_part = 0;
my @datasets;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	
	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}
	unless ($multi_part) {
		my $str = "";

		while (<STDIN>) {
        	       	$str .= $_;
	       	}

		my $space = " ";
		$str =~ s/\x2B/$space/ge;
		my @auth_req = split/&/,$str;

		for my $auth_req_line (@auth_req) {

			my $eqs = index($auth_req_line, "=");	
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1)); 

				
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				if ( $k eq "datasets" ) {
					if ($v eq "students" or $v eq "teachers" or $v =~ /^\d+$/) {
						push @datasets, $v;
					}
				}
				else {
					$auth_params{$k} = $v;
				}
			}
		}
	}
	#processing data sent 
	$post_mode++;
}

my $act = undef;
my $job = undef;
my $create_stage = 0;
my $modem = undef;
my $disconnect_stage = 0;
my $ussd_stage = 1;

my $encd_search_str;
my $search_string;
my $query_mode = 0;

my $message_id = undef;
 
if ( exists $ENV{"QUERY_STRING"} ) {

	if ( $ENV{"QUERY_STRING"} =~ /\&?act=([^\&]+)\&?/i ) {
		$act = lc($1);
	}
	
	if ( $ENV{"QUERY_STRING"} =~ /\&?job=(\d+)\&?/i ) {
		$job = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?create_stage=(\d+)\&?/i ) {
		$create_stage = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?modem=(\d+)\&?/i ) {
		$modem = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?disconnect_stage=([12])\&?/i ) {
		$disconnect_stage = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?ussd_stage=(\d+)\&?/i ) {
		$ussd_stage = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?pg=(\d+)\&?/ ) {	
		$page = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?message_id=(\d+)\&?/ ) {	
		$message_id = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?q=([^&]+)\&?/ ) {	
		$encd_search_str = $1;
		$search_string = $encd_search_str;
		$search_string =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;	
		if ( length($search_string) > 0 ) {
			$query_mode = 1;
		}
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?per_page=(\d+)\&?/ ) {	
			my $possib_per_page = $1;
			
			if (($possib_per_page % 10) == 0) { 	
				$per_page = $possib_per_page;
			}
			else {
				if ($possib_per_page < 10) {
					$per_page = 10;
				}
				else {
					$per_page = substr("".$possib_per_page, 0, -1) . "0";
				}
			}
			#when the user changes the results per
			#page to more results per page, they should
			#be sent a page down.
			#if they select fewer results per page, they should
			#be sent a page up.
			$session{"per_page"} = $per_page;	
	}
}

PM: {
	if ($post_mode) {
	
		if ( defined $act and $act eq "create_job" ) {

			unless ( exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $session{"confirm_code"} eq $auth_params{"confirm_code"} ) {
				$feedback = qq!<p><span style="color: red">No valid confirmation code was sent.</span> Do not alter any of the hidden values in the HTML form.!;
				$create_stage = 1;
				$post_mode = 0;
				last PM;
			}

			#user gives a name,modem[,datasets] for the job
			if ( $create_stage == 2 ) {	
				if ( exists $auth_params{"job_name"} ) {

					my $name = $auth_params{"job_name"};

					unless ( length($name) > 0 ) {	
						$feedback = qq!<p><span style="color: red">A blank job name was posted.</span>!;
						$create_stage = 1;
						$post_mode = 0;
						last PM;
					}

					unless (length($name) < 65) {
						$feedback = qq!<p><span style="color: red">The job name provided is too long.</span> A valid job name should be no more than 64 characters.!;
						$create_stage = 1;
						$post_mode = 0;
						last PM;					
					}
			
						
					if ( exists $auth_params{"modem"} ) {
						my $possib_modem = $auth_params{"modem"};
						if ($possib_modem =~ /^\d+$/) {
							my $modem = $possib_modem;
							
							$session{"job_name"} = $name;
							$session{"modem"} = $modem;
							if (@datasets) {
								$session{"datasets"} = join(",", @datasets);
							}
							#students dataset should be made available by default
							else {
								$session{"datasets"} = "students";
							}
							$create_stage = 3;
							$post_mode = 0;
							last PM;
						}
						else {
							$feedback = qq!<p><span style="color: red">Invalid modem selected.</span>!;
							$create_stage = 1;
							$post_mode = 0;
							last PM;
						}
					}
					else {
						$feedback = qq!<p><span style="color: red">No modem selected.</span>!;
						$create_stage = 1;
						$post_mode = 0;
						last PM;
					}	
				}
				else {
					$feedback = qq!<p><span style="color: red">No job name provided.</span>!;
					$create_stage = 1;
					$post_mode = 0;
					last PM;
				}
			}

			#user has specified a message template
			if ( $create_stage == 4 ) {
				if (exists $session{"job_name"} and exists $session{"modem"} ) {
					if ( exists $auth_params{"message_template"} and length($auth_params{"message_template"}) > 0) {

						my $template = $auth_params{"message_template"};

						if ( length($template) <= 1024 ) {
							#check if any user-uploaded data has been requested
							#this will avoid the need to specify recipients using
							#filters because the selected dataset is a default filter.
							$template =~ s/\r\n/\t/g;
							$template =~ s/\n/\t/g;
							$session{"message_template"} = $template;
							my $relative_validity = 720;

							if (exists $auth_params{"expiry"} and $auth_params{"expiry"} =~ /^\d+$/) {
								$relative_validity = $auth_params{"expiry"};
							}
							$session{"message_validity"} = $relative_validity;

							if ($session{"datasets"} =~ /^\d+$/) {
								$create_stage = 7;
							}

							else {
								$session{"db_filter_type"} = "students";

								if ($session{"datasets"} =~ /teachers/ or $template =~ /<<teachers\.(?:(?:id)|(?:name)|(?:subjects)|(?:lessons))>>/) {
									$session{"db_filter_type"} = "teachers";
								}
								$create_stage = 5;
							}
						}
						else {
							$feedback = qq!<p><span style="color: red">The message template provided is too long.</span> Please enter a template less that .!;
							$create_stage = 3;
						}
					}
				}
				else {
					$feedback = qq!<p><span style="color: red">This job does not appear correctly initialized.</span> Please restart the process.!;
					$create_stage = 1;
				}
				$post_mode = 0;
				last PM;
			}

			#process dataset filters
			if ( $create_stage == 6 ) {

				if ( exists $session{"job_name"} and exists $session{"modem"} and exists $session{"message_template"} ) {

					my @limit_classes = ();
					my @limit_tas_classes = ();
					my @limit_tas_subjects = ();

					for my $param (keys %auth_params) {
						if ($param =~ /^filter_class_/) {
							push @limit_classes, $auth_params{$param};
						}
						elsif ($param =~ /^filter_teachers_class/) {
							push @limit_tas_classes, $auth_params{$param};
						}
						elsif ($param =~ /^filter_teachers_subject/) {
							push @limit_tas_subjects, $auth_params{$param};
						}
					}

					if (@limit_classes) {
						$session{"db_filter"} = lc(join(",", @limit_classes));
					}
					elsif ( @limit_tas_subjects ) {
						if ( @limit_tas_classes ) {

							my @limit_tas_subject_class;

							for my $ta_subject (@limit_tas_subjects) {
								my $classes = join (",", @limit_tas_classes);	
								push @limit_tas_subject_class, lc("$ta_subject($classes)");	
							}

							$session{"db_filter"} = join(";", @limit_tas_subject_class);

						}
					}
					$create_stage = 7;
				}
				else {
					$feedback = qq!<p><span style="color: red">This job does not appear correctly initialized.</span> Please restart the process.!;
					$create_stage = 1;
				}
				$post_mode = 0;
				last PM;
			}

			if ( $create_stage == 8 ) {
				if (exists $auth_params{"commit"} and $auth_params{"commit"} eq "1") {
					$post_mode = 0;
					$create_stage = 7;
					last PM;
				}
				else { 
					$feedback = qq!<p><span style="color: red">This job does not appear correctly initialized.</span> Please restart the process.!;
					$create_stage = 1;
				}
			}	
			
		}
		if ( defined $act and $act eq "disconnect_modem" ) {
			$post_mode = 0;
		}
		elsif (defined $act and $act eq "unlock_modem") {
			

			if (defined $modem) {

				my ($imei,$description,$enabled) = (undef, undef, 0);

				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				my $prep_stmt6 = $con->prepare("SELECT imei,description FROM modems WHERE id=? LIMIT 1");
			
				if ($prep_stmt6) {
					my $rc = $prep_stmt6->execute($modem);

					if ($rc) {
						while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
							$imei = $rslts[0];
							$description = $rslts[1];
							#$enabled = $rslts[2]; 
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
					}	
				}
				else {
					print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
				}

				if (defined $imei) {

					my $modem_obj = undef;
					my $modem_iface = undef;
					my $props_iface = undef;

					use Net::DBus qw(:typing);;
					use Net::DBus::Reactor;

					if ( $modem_manager1 ) {

						eval {
							my $bus = Net::DBus->system;
							my $modem_manager = $bus->get_service("org.freedesktop.ModemManager1");

							my $mm_obj = $modem_manager->get_object("/org/freedesktop/ModemManager1");
							my $mm_obj_manager = $mm_obj->as_interface("org.freedesktop.DBus.ObjectManager");

							my $modem_list = $mm_obj_manager->GetManagedObjects();

							if (ref $modem_list eq "HASH") {

								for my $modem_path ( keys %{$modem_list} ) {

									$modem_obj = $modem_manager->get_object($modem_path);
									$props_iface = $modem_obj->as_interface("org.freedesktop.DBus.Properties");
									$modem_iface = $modem_obj->as_interface("org.freedesktop.ModemManager1.Modem");

									my $modem_description = uc($props_iface->Get("org.freedesktop.ModemManager1.Modem", "Manufacturer") . " " . $props_iface->Get("org.freedesktop.ModemManager1.Modem", "Model"));
									my $modem_imei = $props_iface->Get("org.freedesktop.ModemManager1.Modem", "EquipmentIdentifier");

									if ($modem_imei eq $imei and $modem_description eq $description) {
										last;
									}
									else {
										$modem_obj = undef;
									}

								}

							}

						};

						if ($@) {
							print STDERR "Could not unlock modem $modem: $@\n";
						}

					}
					#modemmanager 0.6
					else {
						#wrapped in an eval--DBus/ModemManager
						eval {
							my $bus = Net::DBus->system;	
							my $modem_manager = $bus->get_service("org.freedesktop.ModemManager");

							#$content = dbus_dump($modem_manager);

							my $get_list = $modem_manager->get_object("/org/freedesktop/ModemManager", "org.freedesktop.ModemManager");
							my $list_modems = $get_list->EnumerateDevices();
							 
							#there're some modems attached
							if (ref($list_modems) eq "ARRAY") {
		
								for my $modem_name (@{$list_modems}) {
									
									$modem_obj = $modem_manager->get_object($modem_name);
									$props_iface = $modem_obj->as_interface("org.freedesktop.DBus.Properties");	

									$modem_iface = $modem_obj->as_interface("org.freedesktop.ModemManager.Modem");

									my @description_bts = @{$modem_iface->GetInfo()};
									my $modem_description = uc("$description_bts[0] $description_bts[1]");
									my $modem_imei = $props_iface->Get("org.freedesktop.ModemManager.Modem", "EquipmentIdentifier");

									#same modem
									#i check both the description and 
									#the imei because there're a lot of
									#fishy phones that pick IMEIs at random
									#but not too many that pick both IMEIs
									#and make/models at random.
									if ($modem_imei eq $imei and $modem_description eq $description) {	
										last;
									}
									else {
										$modem_obj = undef;
									}
								}
							}
						};

						if ($@) {
							print STDERR "Could not unlock modem $modem: $@\n";
						}
					}
					
					if (defined $modem_obj) {

			if (exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $session{"confirm_code"} eq $auth_params{"confirm_code"}) {

				if (exists $auth_params{"unlock_type"} and ($auth_params{"unlock_type"} eq "pin" or  $auth_params{"unlock_type"} eq "puk") ) {

					my ($code_1, $code_2) = (undef, undef);
					
					if ( exists $auth_params{"code_1"} and length($auth_params{"code_1"}) > 0 ) {

						my $valid_request = 1;

						$code_1 = $auth_params{"code_1"};

						my $unlock_type = $auth_params{"unlock_type"};

						if ( $unlock_type eq "puk" ) {
							if ( exists $auth_params{"code_2"} and length($auth_params{"code_2"}) > 0 ) {
								if ( exists $auth_params{"code_3"} and length($auth_params{"code_3"}) > 0 and $auth_params{"code_2"} eq $auth_params{"code_3"}) {
									$code_2 = $auth_params{"code_2"};
									$valid_request = 2;
								}
								else {
									$feedback = qq!<span style="color: red">Invalid request</span>. The new unlock codes do not match.!;
									$valid_request = 0;
								}
							}
							else {
								$feedback = qq!<span style="color: red">Invalid request</span>. A new unlock code was not provided.!;
								$valid_request = 0;
							}
						}

						if ( $valid_request ) {
							my $locked = undef;
							eval {

								if ($modem_manager1) {	

									my $sim_iface = $modem_obj->as_interface("org.freedesktop.ModemManager1.Sim");

									if ($valid_request == 1) {
										$sim_iface->SendPin($code_1);
									}
									else {
										$sim_iface->SendPin($code_1, $code_2);
									}
									$locked = $props_iface->Get("org.freedesktop.ModemManager1.Modem", "UnlockRequired");
									
									#locked == 1 if successfully unlocked
									unless ( $locked == 1 ) {

										$feedback .= qq!<p><span style="color: red>Incorrect unlock code.</span>!;

										my $retries = $props_iface->Get("org.freedesktop.ModemManager1.Modem", "UnlockRetries");
										#check if PIN retries in retries hash
										if ( $valid_request == 1) {

											if ( exists $retries->{2} and $retries->{2} =~ /^\d+$/ ) {

												my $num_retries = $retries->{2};
												$feedback .= " You have $num_retries retries.";
	
											}

										}
										#check if PUK retries in retries hash
										elsif ( exists $retries->{4} and $retries->{4} =~ /^\d+$/) {

											my $num_retries = $retries->{4};
											$feedback .= " You have $num_retries retries.";

										}
									}
									
								}
								else {

									#try unlock
									my $gsm_card_iface = $modem_obj->as_interface("org.freedesktop.ModemManager.Modem.Gsm.Card");
									if ($valid_request == 1) {
										$gsm_card_iface->SendPin($code_1);
									}
									else {
										$gsm_card_iface->SendPuk($code_1, $code_2);
									}

									#check if unlocked
									$locked = $props_iface->Get("org.freedesktop.ModemManager.Modem", "UnlockRequired");

									unless ($locked eq "") {

										$feedback .= qq!<p><span style="color: red>Incorrect unlock code.</span>!;

										my $retries = $props_iface->Get("org.freedesktop.ModemManager.Modem", "UnlockRetries");
									
										#999 means unlimited retries
										unless ($retries == 999) {
											$feedback .= " You have $retries retries.";
										}
									}
								}
							};

							#log error
							if ($@) {
								print STDERR "Could not unlock modem $modem: $@\n";
							}

							#unlock state has changed; update DB
							if ( defined $locked ) {
								my $prep_stmt9 = $con->prepare("UPDATE modems SET locked=? WHERE id=? LIMIT 1");
							
								if ($prep_stmt9) {
									my $rc = $prep_stmt9->execute($locked, $modem);
									if ($rc) {
										$con->commit();
									}
									else {	
										print STDERR "Could not execute UPDATE modems: ", $con->errstr, $/;
									}
								}
								else {
									print STDERR "Could not prepare UPDATE modems: ", $con->errstr, $/;
								}

								#log modem unlock
								my @today = localtime;	
								my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
							
								open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

	      	 						if ($log_f) {

       									@today = localtime;	
									my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
									flock ($log_f, LOCK_EX) or print STDERR "Could not log unlock modem for 1 due to flock error: $!$/";
									seek ($log_f, 0, SEEK_END);
									
									print $log_f "1 MODEM UNLOCK $modem $time\n";	

									flock ($log_f, LOCK_UN);
       									close $log_f;
       								}
								else {
									print STDERR "Could not log unlock modem for 1: $!\n";
								}

							}
						}
					}
					else {
						$feedback = qq!<span style="color: red">Invalid request</span>. No unlock code was provided.!;
					}
				}
				else {
					$feedback = qq!<span style="color: red">Invalid request</span>.!;
				}

				$act = "view_modem";

			}
			else {
				$feedback = qq!<span style="color: red">Invalid request</span>.!
			}
					}
					else {
						$feedback =  qq!<span style="color: red">Selected modem does not exist.</span>. Perhaps it was removed.!;
						undef $act;
					}
				}
				else {
					$feedback =  qq!<span style="color: red">Selected modem does not exist.</span>. New modems are added during creation of messaging jobs.!;
					undef $act;
				}
			}
			else {
				$feedback =  qq!<span style="color: red">No modem selected for unlocking.</span>.!;
				undef $act;
			}
			$post_mode = 0;
		}

		elsif (defined $act and $act eq "view_inbox") {

			if (defined $modem) {

				my ($imei,$description,$enabled) = (undef, undef, 0);

				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				my $prep_stmt6 = $con->prepare("SELECT imei,description FROM modems WHERE id=? LIMIT 1");
			
				if ($prep_stmt6) {
					my $rc = $prep_stmt6->execute($modem);

					if ($rc) {
						while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
							$imei = $rslts[0];
							$description = $rslts[1];
							#$enabled = $rslts[2]; 
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
					}	
				}
				else {
					print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
				}

				if (defined $imei) {
					if (exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $session{"confirm_code"} eq $auth_params{"confirm_code"}) {
						if ( exists $auth_params{"read"} or exists $auth_params{"unread"} ) {
							my @msg_ids = ();
							for my $auth_param (keys %auth_params) {
								if ($auth_param =~ /^message_id_(\d+)$/) {
									my $id = $1;
									#just in case
									if ($auth_params{$auth_param} eq $id) {
										push @msg_ids, $id;
									}
								}
							}
							if (scalar(@msg_ids)) {
								
								#assume mark as read.
								my $new_status = 2;
								if (exists $auth_params{"unread"}) {
									$new_status = 0;
								}

								my @where_clause_bts = ();
								foreach (@msg_ids) {
									push @where_clause_bts, "message_id=?";
								}
	
								my $where_clause = join(" OR ", @where_clause_bts);

								my $prep_stmt6 = $con->prepare("UPDATE inbox SET message_read=$new_status WHERE modem=? AND ($where_clause)");

								if ($prep_stmt6) {
									my $rc = $prep_stmt6->execute($modem, @msg_ids);
									if ($rc) {
										$con->commit();
									}
									else {
										print STDERR "Could not execute UPDATE inbox: ", $con->errstr, $/;
									}
								}
								else {
									print STDERR "Could not prepare UPDATE inbox: ", $con->errstr, $/;
								}

							}
							else {
								$feedback = qq!<span style="color: red">You did not select any messages to re-label as un/read.</span>.!;
							}
						}
						else {
							$feedback = qq!<span style="color: red">Invalid request</span>.!;
						}
					}
					else {
						$feedback = qq!<span style="color: red">Invalid request</span>.!;
					}
				}
				else {
					$feedback =  qq!<span style="color: red">Selected modem does not exist.</span>.!;
					undef $act;
				}
			}
			else {
				$feedback =  qq!<span style="color: red">No modem selected.</span>.!;
				undef $act;
			}
			$post_mode = 0;
		}
		#ussd rquest
		elsif (defined $act and $act eq "ussd_request") {
			#clear any previous USSD request.
			#initiate new request	
			if (exists $session{"modem_path"} and defined $modem) {

				my $modem_name = $session{"modem_path"};

				if ( exists $auth_params{"confirm_code"} and exists $session{"confirm_code"} and $auth_params{"confirm_code"} eq $session{"confirm_code"} ) {

					if ($ussd_stage == 2) {

						if ( exists $auth_params{"mmi_code"} ) {

							my $mmi_code = $auth_params{"mmi_code"};
	
							#valid MMI code
							if ( $mmi_code =~ /^[\*#][\*#]?\d+(\*\d+)*\#$/ ) {

								my $modem_seen = 0;
								my $response = undef;
								my $active = 0;

								use Net::DBus qw(:typing);

								if ($modem_manager1) {
									eval {

										my $bus = Net::DBus->system;	
										my $modem_manager = $bus->get_service("org.freedesktop.ModemManager1");

										my $modem_obj = $modem_manager->get_object($modem_name);
										$modem_seen++;

										my $props_iface = $modem_obj->as_interface("org.freedesktop.DBus.Properties");
										my $ussd_iface = $modem_obj->as_interface("org.freedesktop.ModemManager1.Modem.Modem3gpp.Ussd");
										my $state = $props_iface->Get("org.freedesktop.ModemManager1.Modem.Modem3gpp.Ussd", "State");
										if ( $state == 2 or $state == 3 ) {
											$ussd_iface->Cancel();
										}
										
										$response = $ussd_iface->Initiate($mmi_code);

										$state = $props_iface->Get("org.freedesktop.ModemManager1.Modem.Modem3gpp.Ussd", "State");

										if ($state == 2 or $state == 3) {
											$active = 1;
										}
								
									};
								}
								else {	
									#wrapped in an eval--DBus/ModemManager
									eval {
									my $bus = Net::DBus->system;	
									my $modem_manager = $bus->get_service("org.freedesktop.ModemManager");

									my $modem_obj = $modem_manager->get_object($modem_name);
									$modem_seen++;

									my $props_iface = $modem_obj->as_interface("org.freedesktop.DBus.Properties");
									my $gsm_ussd_iface = $modem_obj->as_interface("org.freedesktop.ModemManager.Modem.Gsm.Ussd");

									my $state = $props_iface->Get("org.freedesktop.ModemManager.Modem.Gsm.Ussd", "State");
	

									if ( $state eq "active" or $state eq "user-response" ) {
										$gsm_ussd_iface->Cancel();
									}
	
									$response = $gsm_ussd_iface->Initiate($mmi_code);

									$state = $props_iface->Get("org.freedesktop.ModemManager.Modem.Gsm.Ussd", "State");
									if ( $state eq "active" or $state eq "user-response" ) {
										$active = 1;	
									}

									};
								}

								#error was experienced
								if ($@) {

									my $error = $@;

									if ($modem_seen) {
										$feedback = qq!<span style="color: red">An error was experienced while initiating the USSD request.</span> $error!;
										$act = "ussd_request";
										$ussd_stage = 1;
										$post_mode = 0;
										last PM;
									}
									#modem was not seen; perhaps it's not connected
									else {
										$feedback = qq!<span style="color: red">Could not detect modem.</span> Perhaps it was disconnected.!;
										$act = "view_modem";	
										$post_mode = 0;
										last PM;
									}
								}

								#a server response was received 
								if ( defined $response ) {

									#do HTML newlines
									$response = htmlspecialchars($response);

									$response =~ s/\r\n/<br>/g;
									$response =~ s/\n/<br>/g;

									

									$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Messenger - Send Messages - USSD Request</title>
</head>

<body>
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/message.cgi">Send Messages</a> --&gt; <a href="/cgi-bin/message.cgi?act=view_modem&modem=$modem">View Modem</a>

<hr>

<h4>Network says:</h4>
<p>$response
*;
									if ($active) {

										my $conf_code = gen_token();
										$session{"confirm_code"} = $conf_code;

										$content .=
qq*
<FORM method="POST" action="/cgi-bin/message.cgi?act=ussd_request&ussd_stage=3&modem=$modem">

<TABLE>

<TR><TD><LABEL>Reply</LABEL><TD><INPUT type="text" name="reply" value="">
<TR><TD><INPUT type="submit" name="send" value="Send"><TD><INPUT type="submit" name="cancel" value="Cancel">

</TABLE>
<INPUT type="hidden" name="confirm_code" value="$conf_code">
</FORM>
*;
								
									}
									#unset modem path
									else {
										delete $session{"modem_path"};
									}

									$content .=
qq*
</body>
</html>
*;
								}

								#log USSD request
								my @today = localtime;	
								my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
							
								open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

	      	 						if ($log_f) {

       									@today = localtime;	
									my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
									flock ($log_f, LOCK_EX) or print STDERR "Could not log USSD request for 1 due to flock error: $!$/";
									seek ($log_f, 0, SEEK_END);
											
									print $log_f "1 USSD REQUEST $mmi_code $time\n";
							
									flock ($log_f, LOCK_UN);
       									close $log_f;
       								}
								else {
									print STDERR "Could not log USSD request for 1: $!\n";
								}

							}
							else {
								$feedback =  qq!<span style="color: red">Invalid request received.</span>. Invalid MMI code given.!;
								$act = "ussd_request";
								$ussd_stage = 1;
								$post_mode = 0;
								last PM;
							}
						}
						else {
							$feedback =  qq!<span style="color: red">Invalid request received.</span>. No MMI code given.!;
							$act = "ussd_request";
							$ussd_stage = 1;
							$post_mode = 0;
							last PM;
						}
					}

					elsif ( $ussd_stage == 3 ) {
	
						my $success = 0;
	
						#user wants to cancel
						my $cancel = 0;
						my $proc_user_reply = 0;
						my $user_reply = undef;

						if ( exists $auth_params{"cancel"} and $auth_params{"cancel"} eq "Cancel" ) {
							$cancel++;
						}
						elsif (exists $auth_params{"send"} and $auth_params{"send"} eq "Send" ) {
							$proc_user_reply++;
							if ( exists $auth_params{"reply"} and length($auth_params{"reply"}) > 0 ) {
								$proc_user_reply++;
								$user_reply = $auth_params{"reply"};
							}
							else {
								$feedback = qq!<span style="color: red">No reply sent when one expected.</span>!;
								$act = "ussd_request";
								$ussd_stage = 1;
								$post_mode = 0;
								last PM;
							}
						}
	
						my $modem_seen = 0;
						my $response = undef;
						my $active = 0;
							
						use Net::DBus qw(:typing);

						if ($modem_manager1) {
							eval {

								my $bus = Net::DBus->system;	
								my $modem_manager = $bus->get_service("org.freedesktop.ModemManager1");

								my $modem_obj = $modem_manager->get_object($modem_name);
								$modem_seen++;

								my $props_iface = $modem_obj->as_interface("org.freedesktop.DBus.Properties");
								my $ussd_iface = $modem_obj->as_interface("org.freedesktop.ModemManager1.Modem.Modem3gpp.Ussd");
								my $state = $props_iface->Get("org.freedesktop.ModemManager1.Modem.Modem3gpp.Ussd", "State");
								
								if ( $state == 2 or $state == 3 ) {
									if ($cancel) {
										$ussd_iface->Cancel();
									}
									elsif ($proc_user_reply == 2) {	
										$response = $ussd_iface->Respond($user_reply);
									}
								}

								$state = $props_iface->Get("org.freedesktop.ModemManager1.Modem.Modem3gpp.Ussd", "State");

								if ($state == 2 or $state == 3) {
									$active = 1;
								}
								$success++;
							};
						}
						else {	
							#wrapped in an eval--DBus/ModemManager
							eval {
								my $bus = Net::DBus->system;	
								my $modem_manager = $bus->get_service("org.freedesktop.ModemManager");

								my $modem_obj = $modem_manager->get_object($modem_name);
								$modem_seen++;
								

								my $props_iface = $modem_obj->as_interface("org.freedesktop.DBus.Properties");
								my $gsm_ussd_iface = $modem_obj->as_interface("org.freedesktop.ModemManager.Modem.Gsm.Ussd");

								my $state = $props_iface->Get("org.freedesktop.ModemManager.Modem.Gsm.Ussd", "State");
	

								if ( $state eq "active" or $state eq "user-response" ) {

									if ($cancel) {	
										$gsm_ussd_iface->Cancel();
									}
									#valid user reply
									elsif ($proc_user_reply == 2) {	
										$response = $gsm_ussd_iface->Respond($user_reply);
									}

								}

								$state = $props_iface->Get("org.freedesktop.ModemManager.Modem.Gsm.Ussd", "State");
								if ( $state eq "active" or $state eq "user-response" ) {
									$active = 1;	
								}
								$success++;
							};
						}

						#error was experienced
						if ($@) {

							my $error = $@;

							if ($modem_seen) {
								$feedback = qq!<span style="color: red">An error was experienced while making the USSD request.</span> $error!;
								$act = "ussd_request";
								$ussd_stage = 1;
								$post_mode = 0;
								last PM;
							}
							#modem was not seen; perhaps it's not connected
							else {
								$feedback = qq!<span style="color: red">Could not detect modem.</span> Perhaps it was disconnected.!;
								$act = "view_modem";	
								$post_mode = 0;
								last PM;
							}
						}

						if ($success) {
							$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Messenger - Send Messages - USSD Request</title>
</head>

<body>
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/message.cgi">Send Messages</a> --&gt; <a href="/cgi-bin/message.cgi?act=view_modem&modem=$modem">View Modem</a>

<hr>
*;

							#cancel
							if ($cancel) {
								$content .= "<em>USSD Request successfully canceled.</em>";
								delete $session{"modem_path"};
							}
							#user reply 
							elsif ($proc_user_reply == 2) {
								#do HTML newlines
								$response = htmlspecialchars($response);

								$response =~ s/\r\n/<br>/g;
								$response =~ s/\n/<br>/g;

								$content .=
qq!
<h4>Network says:</h4>
<p>$response
!;
								if ($active) {
									my $conf_code = gen_token();
									$session{"confirm_code"} = $conf_code;

									$content .=
qq*
<FORM method="POST" action="/cgi-bin/message.cgi?act=ussd_request&ussd_stage=3&modem=$modem">

<TABLE>

<TR><TD><LABEL>Reply</LABEL><TD><INPUT type="text" name="reply" value="">
<TR><TD><INPUT type="submit" name="send" value="Send"><TD><INPUT type="submit" name="cancel" value="Cancel">

</TABLE>
<INPUT type="hidden" name="confirm_code" value="$conf_code">
</FORM>
*;
								}
								else {
									delete $session{"modem_path"};
								}
							}
							$content .=
qq*
</body>
</html>
*;
						}
					}
				}
				else {
					$feedback =  qq!<span style="color: red">Invalid request received.</span>. Please retry.!;
					$act = "ussd_request";
					$ussd_stage = 1;
					$post_mode = 0;
					last PM;
				}
			}
			else {
				$feedback =  qq!<span style="color: red">Invalid request received.</span>. Please retry.!;
				$act = "view_modem";
				$ussd_stage = 1;
				$post_mode = 0;
				last PM;
			}
			$post_mode = 0;
		}

		elsif (defined $act and $act eq "send_message") {
			#clear any previous USSD request.
			#initiate new request	
			if (exists $session{"modem_path"} and defined $modem) {

				my $modem_name = $session{"modem_path"};

				if ( exists $auth_params{"confirm_code"} and exists $session{"confirm_code"} and $auth_params{"confirm_code"} eq $session{"confirm_code"} ) {

					if (exists $auth_params{"recipient"} and $auth_params{"recipient"} =~ /^\d+$/) {	

						my $recipient = $auth_params{"recipient"};
						my $message = " ";

						if ( exists $auth_params{"message"} and length($auth_params{"message"}) > 0) {
							$message = $auth_params{"message"};
						}

						my $relative_validity = 720;

						if (exists $auth_params{"expiry"} and $auth_params{"expiry"} =~ /^\d+$/) {
							$relative_validity = $auth_params{"expiry"};
						}

						my ($success,$modem_seen) = (0,0);
						use Net::DBus qw(:typing);


						if ($modem_manager1) {
							eval {

								my $bus = Net::DBus->system;	
								my $modem_manager = $bus->get_service("org.freedesktop.ModemManager1");

								my $modem_obj = $modem_manager->get_object($modem_name);
								$modem_seen++;

								my $messaging_iface = $modem_obj->as_interface("org.freedesktop.ModemManager1.Modem.Messaging");

								my $sms_props = { "Number" => $recipient, "Text" => $message };

								my $sms_path = $messaging_iface->Create($sms_props);
								my $sms_obj = $modem_manager->get_object($sms_path);
									
								my $sms_iface = $sms_obj->as_interface("org.freedesktop.ModemManager1.Sms");

								$sms_iface->Send();

								$success++;
							};
						}
						else {	
							#wrapped in an eval--DBus/ModemManager
							eval {
								my $bus = Net::DBus->system;	
								my $modem_manager = $bus->get_service("org.freedesktop.ModemManager");

								my $modem_obj = $modem_manager->get_object($modem_name);
								$modem_seen++;

								my $gsm_sms_iface = $modem_obj->as_interface("org.freedesktop.ModemManager.Modem.Gsm.SMS");
								
								my $result = $gsm_sms_iface->Send({"number" => $recipient, "text" => $message, "relative-validity" => $relative_validity});
							
								$success++;
							};
						}

						#error was experienced
						if ($@) {
	
							my $error = $@;

							if ($modem_seen) {
								$feedback = qq!<span style="color: red">An error was experienced while sending the message.</span> $error!;
								$act = "send_message";
								$post_mode = 0;
								last PM;
							}
							#modem was not seen; perhaps it's not connected
							else {
								$feedback = qq!<span style="color: red">Could not detect modem.</span> Perhaps it was disconnected.!;
								$act = "view_modem";	
								$post_mode = 0;
								last PM;
							}
						}
	
						if ($success) {
							$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Messenger - Send Messages - Modems</title>
</head>

<body>
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/message.cgi">Send Messages</a> --&gt; <a href="/cgi-bin/message.cgi?act=view_modem&modem=$modem">View Modem</a>

<hr>
<p><span style="color: green">Message successfully sent!</span>
</body>
</html>
*;
							#log message send
							$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

							my $prep_stmt2 = $con->prepare("INSERT INTO sent_messages VALUES (NULL,?,?,?,?)");

							my @time_bts = localtime();
							my $time = sprintf("%d/%02d/%02d %02d:%02d:%02d", ($time_bts[5] + 1900), ($time_bts[4] + 1), $time_bts[3], $time_bts[2], $time_bts[1], $time_bts[0]);

							if ($prep_stmt2) {
								my $rc = $prep_stmt2->execute($modem,$recipient,$message,$time);
								
								if ($rc) {
									$con->commit();
								}
								else {
									print STDERR "Could not execute INSERT INTO sent_messages: ", $con->errstr, $/;
								}
							}
							else {
								print STDERR "Could not prepare SELECT FROM sent_messages: ", $con->errstr, $/;
							}
						}
					}
					else {

					}
				}
				else {
					$feedback =  qq!<span style="color: red">Invalid request received.</span>. Please retry.!;
					$act = "send_message";	
					$post_mode = 0;
					last PM;
				}
			}
			else {
				$feedback =  qq!<span style="color: red">Invalid request received.</span>. Please retry.!;
				$act = "view_modem";	
				$post_mode = 0;
				last PM;
			}	
		}
	}
}

if (not $post_mode) {

	if ( defined $act and $act eq "restart_job" ) {
	
		if ( defined $job ) {

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my ( $name,$modem,$message_template,$message_validity,$db_filter_type, $db_filter, $datasets, $instructions ) = ( undef, undef, undef, undef, undef, undef, undef, undef );

			#get pid of jobs to suspend before deleting them 
			my $prep_stmt8 = $con->prepare("SELECT name,modem,message_template,message_validity,db_filter_type,db_filter,datasets,instructions FROM messaging_jobs WHERE id=? LIMIT 1");

			if ($prep_stmt8) {

				my $rc = $prep_stmt8->execute($job);

				if ($rc) {

					while ( my @rslts = $prep_stmt8->fetchrow_array() ) {

						$name = $rslts[0];
						$modem = $rslts[1];
						$message_template = $rslts[2];
						$message_validity = $rslts[3];
						$db_filter_type = $rslts[4];
						$db_filter = $rslts[5];
						$datasets = $rslts[6];
						$instructions = $rslts[7];

					}
				}
				else {
					print STDERR "Could not execute SELECT FROM messaging_jobs: ", $con->errstr, $/;
				}
			}

			else {
				print STDERR "Could not prepare SELECT FROM messaging_jobs: ", $con->errstr, $/;
			}

			#h
			if (defined $name) {
				#job must be suspended
				$auth_params{"commit"} = 1;
				#save session keys
				$session{"job_name"} = $name;
				$session{"modem"} = $modem;
				$session{"message_template"} = $message_template;
				$session{"message_validity"} = $message_validity;

				if ( length($db_filter_type) > 0 ) {
					$session{"db_filter_type"} = $db_filter_type;
					$session{"db_filter"} = $db_filter;	
				}
				if ( length($datasets) > 0 ) {
					$session{"datasets"} = $datasets;
				}

				#log resume
				my @today = localtime;	
				my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
					
				open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

  				if ($log_f) {

					my $space = " ";
					my $job_name = $name;
					$job_name =~ s/\x2B/$space/ge;
					$job_name =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
					$job_name = htmlspecialchars($job_name);

      					@today = localtime;	
					my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
					flock ($log_f, LOCK_EX) or print STDERR "Could not log resume messaging job for 1 due to flock error: $!$/";
					seek ($log_f, 0, SEEK_END);
				
					print $log_f "1 RESTART MESSAGING JOB $job_name $time\n";
					flock ($log_f, LOCK_UN);
       					close $log_f;

       				}
				else {
					print STDERR "Could not log create messaging job for 1: $!\n";
				}

				$create_stage = 7;
				$act = "create_job";

			}
			else {
				$feedback = qq!<p><span style="color: red">The job specified does not exist.</span>!;
				undef $act;
			}
		}
		else {

			$feedback = qq!<p><span style="color: red">No job specified.</span>!;
			undef $act;
		}
	}

	if ( defined $act and $act eq "resume_job" ) {
	
		if ( defined $job ) {

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my ($job_name, $instructions) = (undef, undef);
			my $space = " ";
			#get pid of jobs to suspend before deleting them 
			my $prep_stmt8 = $con->prepare("SELECT name,instructions FROM messaging_jobs WHERE id=? LIMIT 1");

			if ($prep_stmt8) {

				my $rc = $prep_stmt8->execute($job);

				if ($rc) {

					while ( my @rslts = $prep_stmt8->fetchrow_array() ) {
						$job_name = $rslts[0];

						$job_name =~ s/\x2B/$space/ge;
						$job_name =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
						$job_name = htmlspecialchars($job_name);

						$instructions = $rslts[1];
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM messaging_jobs: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM messaging_jobs: ", $con->errstr, $/;
			}

			if (defined $instructions) {

				if ( $instructions == 2 ) {
					
					my $pid = fork;

					#child
					if ($pid == 0) {
	
						use POSIX;

						close STDIN;
						close STDOUT;
						close STDERR;

						POSIX::setsid();

						exec "perl", "/usr/local/bin/spanj_sms.pl", $job;
						exit 0;
					}
					#parent
					else {

						$SIG{CHLD} = 'IGNORE';

						#log resume
						my @today = localtime;	
						my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
						
						open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

      	 					if ($log_f) {

       							@today = localtime;	
							my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
							flock ($log_f, LOCK_EX) or print STDERR "Could not log resume messaging job for 1 due to flock error: $!$/";
							seek ($log_f, 0, SEEK_END);
				
							print $log_f "1 RESUME MESSAGING JOB $job_name $time\n";
							flock ($log_f, LOCK_UN);
       							close $log_f;

       						}
						else {
							print STDERR "Could not log create messaging job for 1: $!\n";
						}
						
						$content = 
qq*
<!DOCTYPE html>

<html lang="en">

<head>
<title>Messenger - Send Messages - Create new Job</title>
</head>

<body>

$header
<span style="color: green">Starting messaging job.</span> Would you like to <a href="/cgi-bin/message.cgi?act=view_job&job=$job">view the running job</a>?

</body>
</html>
*;
					}
				}
				else {
					$feedback = qq!<p><span style="color: red">This job is currently not suspended.</span> Would you like to <a href="/cgi-bin/message.cgi?act=suspend_job&job=$job">suspend it now</a>?!;
					$act = "view_job";
				}
			}
			else {
				$feedback = qq!<p><span style="color: red">The job specified does not exist.</span>!;
				undef $act;
			}
		}
		else {
			$feedback = qq!<p><span style="color: red">No job specified.</span>!;
			undef $act;
		}
	}

	if ( defined $act and $act eq "view_job_messages" ) {
	
		if ( defined $job ) {

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my $name = undef;
			
			#get pid of jobs to suspend before deleting them 
			my $prep_stmt8 = $con->prepare("SELECT name FROM messaging_jobs WHERE id=? LIMIT 1");

			if ($prep_stmt8) {

				my $rc = $prep_stmt8->execute($job);

				if ($rc) {
					while ( my @rslts = $prep_stmt8->fetchrow_array() ) {
						$name = $rslts[0];	
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM messaging_jobs: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM messaging_jobs: ", $con->errstr, $/;
			}

			if (defined $name) {
				my %msgs = ();

				my $prep_stmt2 = $con->prepare("SELECT message_id,recipient,text,sent FROM outbox WHERE messaging_job=?");
			
				if ($prep_stmt2) {

					my $rc = $prep_stmt2->execute($job);

					if ($rc) {
						while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
							$msgs{$rslts[0]} = { "recipient" => $rslts[1], "text" => $rslts[2], "sent" => $rslts[3] };
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM outbox: ", $con->errstr, $/;
					}
				}

				else {
					print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
				}

				my $rslts_table = "<em>There are no messages in this job.</em>";

				if ( scalar(keys %msgs) > 0 ) {

					$rslts_table = 
qq!
<TABLE border="1">
<THEAD>
<TH>Recipient<TH>Text<TH>Status
</THEAD>
<TBODY>
!;
					for my $msg ( sort { ${$msgs{$b}}{"sent"} <=> ${$msgs{$a}}{"sent"} } keys %msgs ) {
	
						my $text = htmlspecialchars(${$msgs{$msg}}{"text"});
						my $status = "NOT sent";
					
						my $time = ${$msgs{$msg}}{"sent"};

						if ( $time > 0 ) {
							my @time_bts = localtime($time);
							$status = sprintf (qq!<SPAN style="color: green">Sent</SPAN><BR>%02d/%02d/%d %02d:%02d:%02d!, $time_bts[3], ($time_bts[4] + 1), ($time_bts[5] + 1900),  $time_bts[2], $time_bts[1], $time_bts[0]);
						}

						$rslts_table .= qq!<TR><TD>${$msgs{$msg}}{"recipient"}<TD>$text<TD>$status!;
					}
				}
				$rslts_table .= "</TBODY></TABLE>";
	
				$content =
qq*
<!DOCTYPE html>

<html lang="en">

<head>
<title>Messenger - Send Messages - Create new Job</title>
</head>

<body>

$header
$rslts_table

</body>
</html>
*;
		
			}
			else {
				$feedback = qq!<p><span style="color: red">The job specified does not exist.</span>!;
				undef $act;
			}
		}
		else {
			$feedback = qq!<p><span style="color: red">No job specified.</span>!;
			undef $act;
		}
	}
		
	#create a new job
	if ( defined $act and $act eq "create_job" ) {
		#preview outbox
		#allow discarding/saving
		if ($create_stage == 7) {	
			
			if ( exists $session{"job_name"} and exists $session{"modem"} and exists $session{"message_template"} ) {

				my $msg_template = $session{"message_template"};
				my %stud_lookup = ();
				my %class_lookup = ();

				my $space = " ";
				my $new_line = $/;

				$msg_template =~ s/\x2B/$space/ge;	
				$msg_template =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$msg_template =~ s/\t/$new_line/ge;

					
				#what is th time
				my @today = localtime;
				my $current_yr = $today[5] + 1900;

				my (@subjects, @classes);

				my $yrs_study = 4;
				my ($min_class, $max_class) = (undef,undef);

				my $exam = undef;
				my $exam_yr = $current_yr;

				my %points;
				my $rank_partial = 1;
				my %rank_by_points;

				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				my $prep_stmt2 = $con->prepare("SELECT id,value FROM vars WHERE id='1-subjects' OR id='1-classes' OR id='1-exam' OR id='1-grading' OR id='1-rank partial' OR id='1-rank by points' OR id='1-points' LIMIT 7");
	
				if ($prep_stmt2) {
					my $rc = $prep_stmt2->execute();
					if ($rc) {
						while ( my @rslts = $prep_stmt2->fetchrow_array() ) {

							if ($rslts[0] eq "1-subjects") {
								@subjects = split/,/, $rslts[1];
							}
							elsif ($rslts[0] eq "1-classes") {
								@classes = split/,/, $rslts[1];

								foreach (@classes) {
									if ($_ =~ /(\d+)/) {
										my $tst_yr = $1;
										if (not defined $min_class) {
											$min_class = $tst_yr;
											$max_class = $tst_yr;
										}
										else {
											$min_class = $tst_yr if ($tst_yr < $min_class);
											$max_class = $tst_yr if ($tst_yr > $max_class);
										}
									}
									$yrs_study = ($max_class - $min_class) + 1;
								}

							}
							elsif ($rslts[0] eq "1-exam") {

								$exam = $rslts[1];
								if ( $exam =~ /(\d{4})/ ) {
									$exam_yr = $1;
								}

							}
							elsif ($rslts[0] eq "1-grading") {
								my $grading_str = $rslts[1];
								my @grading_bts = split/,/,$grading_str;
								foreach (@grading_bts) {
									if ($_ =~ /^([^:]+):\s*(.+)$/) {
										my ($condition,$grade) = ($1,$2);
										#greater than (>|>=)
										#set min value
										if ($condition =~ /^\s*>\s*(\d+)$/) {
											${$grading{$grade}}{"min"} = $1
										}
										elsif ($condition =~ /^\s*>=\s*(\d+)$/) {
											my $min = $1;
											$min--;
											${$grading{$grade}}{"min"} = $min;
										}
										#less than (<|<=)
										#set max value of condition
										elsif ($condition =~ /^\s*<\s*(\d+)$/) {
											${$grading{$grade}}{"max"} = $1
										}
										elsif ($condition =~ /^\s*<=\s*(\d+)$/) {
											my $max = $1;
											$max++;
											${$grading{$grade}}{"max"} = $max;
										}
										#handle ranges
										#x-y
										elsif ($condition =~ /^\s*(\d+)\s*\-\s*(\d+)$/) {
											my ($min,$max) = ($1,$2);
											#don't be hard on users
											#reverse $min & $max if
											#they've been 'jumbled'
											if ($max < $min) {
												my $tmp = $max;
												$max = $min;
												$min = $tmp;
											}
											#the bugs I picked on accnt of not including tht +/-1!
											${$grading{$grade}}{"min"} = $min -1;
											${$grading{$grade}}{"max"} = $max + 1;
										}
										#handle equality (=)
										#set eqs
										elsif ($condition =~ /^\s*=\s*(\d+)$/) {
											${$grading{$grade}}{"eq"} = $1
										}
									}
								}
							}
							#rank a students just by the subjects they've done
							elsif ($rslts[0] eq "1-rank partial") {
								if (defined $rslts[1] and lc($rslts[1]) eq "no") {
									$rank_partial = 0;
								}
							}
							#rank by points
							elsif ( $rslts[0] eq "1-rank by points" ) {

								if ( defined($rslts[1]) and $rslts[1] =~ /^(?:[0-9]+,?)+$/ ) {
							
									my @yrs = split/,/,$rslts[1];
									for my $yr (@yrs) {
										$rank_by_points{$yr}++;
									}
								}
							}
							#points
							elsif ($rslts[0] eq "1-points") {
								my $points_str = $rslts[1];
								my @points_bts = split/,/,$points_str;
								foreach (@points_bts) {
									if ($_ =~ /^([^:]+):\s*(.+)/) {
										my ($grade,$points) = ($1,$2);
										$points{$grade} = $points;	
									}
								}
							}
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM vars: ", $con->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM vars: ", $con->errstr, $/;
				}

				#replace <<students.exam_name>>
				#do this here because this field is universal
				$msg_template =~ s/<<students.exam_name>>/$exam/g;


				#db_filtered--hopefully this will be
				#the most common use scenarion:- a user
				#just wants to send results or timetable
				#updates
				my %recipients = ();
				
				my %dataset_metadata = ();

				O:{

				if (exists $session{"db_filter_type"}) {
	
					#teacher limd
					if ( $session{"db_filter_type"} eq "teachers") {

						my $raw_subjs_filter = $session{"db_filter"};
						my @subjs_filter_bts = split/;/, $raw_subjs_filter;

						my @expanded_subjs_filter_bts = ();

						for my $subjs_filter_bt (@subjs_filter_bts) {
							if ($subjs_filter_bt =~ /^([^\(]+)\(([^\)]+)\)/) {
								my $subj = $1;
								my $classes = $2;
								
								my @classes = split/,/, $classes;

								for my $class (@classes) {
									push @expanded_subjs_filter_bts, "$subj($class)"; 
								}
							}
						}

						my $subjs_filter = join(",", @expanded_subjs_filter_bts);
			
						#read the teachers DB
						my $prep_stmt3 = $con->prepare("SELECT id,subjects FROM teachers");
	
						if ($prep_stmt3) {
							my $rc = $prep_stmt3->execute();
							if ($rc) {
								while ( my @rslts = $prep_stmt3->fetchrow_array() ) {
	
									my $seen = 0;

									#say English[1A(2016),2A(2015)];Kiswahili[3A(2014)]
									my $machine_class_subjs = $rslts[1];
			
									#now i have 
									#[0]: English[1A(2016),2A(2015)]
									#[1]: Kiswahili[3A(2014)]
									my @subj_groups = split/;/, $machine_class_subjs;
									my @reformd_subj_group = ();

									#take English[1A(2016),2A(2015)]
									J: for my $subj_group (@subj_groups) {

										my ($subj,$classes_str);
						
										if ($subj_group =~ /^([^\[]+)\[([^\]]+)\]$/) {
											#English
											my $subj = $1;
											#1A(2016),2A(2015)
											my $classes_str = $2;	
											#[0]: 1A(2016)
											#[1]: 2A(2015)
											my @classes_list = split/,/, $classes_str;
											my @reformd_classes_list = ();

											#take 1A(2016) 	
											for my $class (@classes_list) {	
												if ($class =~ /\((\d+)\)$/) {	
													my $grad_yr = $1;	

													my $class_dup = $class;
													$class_dup =~ s/\($grad_yr\)//;

													if ( $grad_yr >= $current_yr ) {

														my $class_yr = $yrs_study - ($grad_yr - $current_yr);
														$class_dup =~ s/\d+/$class_yr/;

														#is this one of the subjects in the
														if ( index($subjs_filter, lc("$subj($class_dup)")) >= 0) {
															$seen++;
															last J;
														}
													}
												}
											}
										}
									}

									if ( $seen ) {
										$recipients{$rslts[0]} = $msg_template;
									}
								}
							}
							else {
								print STDERR "Could not execute SELECT FROM teachers: ", $con->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare SELECT FROM teachers: ", $con->errstr, $/;
						}

					}
					#student limd
					else {

						my $classes_filter = $session{"db_filter"};	

						my @valid_classes = ();

						my $prep_stmt4 = $con->prepare("SELECT table_name,class,start_year FROM student_rolls");
	
						if ($prep_stmt4) {
							my $rc = $prep_stmt4->execute();
							if ($rc) {

								while ( my @rslts = $prep_stmt4->fetchrow_array() ) {

									my $class = $rslts[1];
									my $yr = ( $current_yr - $rslts[2] ) + 1;

									$class =~ s/\d+/$yr/;
								
	
									if ( index($classes_filter, lc($class)) >= 0 ) {
										push @valid_classes, $rslts[0];
									}

									$class_lookup{lc($class)} = {"table" => $rslts[0], "start_year" => $rslts[2]};
								}
							}
							else {
								print STDERR "Could not execute SELECT FROM student_rolls: ", $con->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare SELECT FROM student_rolls: ", $con->errstr, $/;
						}	

						if (@valid_classes) {
	
							my @where_clause_bts = ();
							foreach (@valid_classes) {
								push @where_clause_bts, "table_name=?";
							}
							my $where_clause = join(" OR ", @where_clause_bts);

							#my $num_rows = scalar(@where_clause_bts);

							#read student tables
							my $prep_stmt5 = $con->prepare("SELECT adm_no,table_name FROM adms WHERE $where_clause");
	
							if ($prep_stmt5) {
								my $rc = $prep_stmt5->execute(@valid_classes);
								if ($rc) {
									while ( my @rslts = $prep_stmt5->fetchrow_array() ) {
										$recipients{$rslts[0]} = $msg_template;
										$stud_lookup{$rslts[0]} = $rslts[1];
									}
								}
								else {
									print STDERR "Could not execute SELECT FROM student_rolls: ", $con->errstr, $/;
								}
							}
							else {
								print STDERR "Could not prepare SELECT FROM student_rolls: ", $con->errstr, $/;
							}	
						}

						#lookup 
					}
				}
				#user has selected some datasets
				#use the LCD.
				else {
					
					my @datasets = split/,/,$session{"datasets"};

					my @where_clause_bts = ();

					my $read_studs_db = 0;
					#my $read_tas_db = 0;

					foreach (@datasets) {
						if ($_ eq "students") {
							$read_studs_db++;
						}
						elsif ($_ eq "teachers") {
							next;
						}
						else {
							push @where_clause_bts, "id=?";
						}
					}

					my $where_clause = join(" OR ", @where_clause_bts);
					my $num_rows = scalar(@datasets);

					$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
					#read dataset metadata	
					my $prep_stmt6 = $con->prepare("SELECT id,foreign_key,link_to FROM datasets WHERE $where_clause LIMIT $num_rows");
	
					if ($prep_stmt6) {
						my $rc = $prep_stmt6->execute(@datasets);
						if ($rc) {
							while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
								$dataset_metadata{$rslts[0]} = $rslts[1];

								if ( $rslts[2] eq "students") {
									$read_studs_db++;
								}
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM datasets: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM datasets: ", $con->errstr, $/;
					}

					my $initd = 0;

					for my $id (keys %dataset_metadata) {

						my @data;
						my $foreign_key_col = $dataset_metadata{$id};

						my $lines = 0;

						open (my $f, "<$upload_dir/$id");

						while ( <$f> ) {

							chomp;
							$lines++;

							my $line = $_;

							my @cols = split/,/,$line;

							KK: for (my $i = 0; $i < (scalar(@cols) - 1); $i++) {
								#escaped
								if ( $cols[$i] =~ /(.*)\\$/ ) {

									my $non_escpd = $1;
									$cols[$i] = $non_escpd . "," . $cols[$i+1];

									splice(@cols, $i+1, 1);
									redo KK;
								}

								#assume that quotes will be employed around
								#an entire field
								#has it been opened?
								if ($cols[$i] =~ /^".+/) {
									#has it been closed? 
									unless ( $cols[$i] =~ /.+"$/ ) {
										#assume that the next column 
										#is a continuation of this one.
										#& that a comma was unduly pruned
										#between them
										$cols[$i] = $cols[$i] . "," . $cols[$i+1];
										splice (@cols, $i+1, 1);
										redo KK;
									}
								}
							}

							for (my $j = 0; $j < @cols; $j++) {
								if ($cols[$j] =~ /^"(.*)"$/) {
									$cols[$j] = $1; 
								}
							}

							if ($lines > 1) {
								push @data, $cols[$foreign_key_col];
							}
						}		

						if (not $initd) {
							foreach ( @data ) {
								$recipients{$_} = $msg_template;
							}
						}
						else {
							#can't add to recipients
							#only chuck existing records
							my %data;
							@data{@data} = @data;

							for my $recipient (keys %recipients) {
								if ( not exists $data{$recipient} ) {
									delete $recipients{$recipient};
								}
							}
						}
					}
	
					#stud adm to stud table lookup
					if ($read_studs_db) {

						my @where_clause_bts = ();

						foreach ( keys %recipients ) {
							push @where_clause_bts, "adm_no=?";
						}

						my $where_clause = join(" OR ", @where_clause_bts);
						my $num_rows = scalar(@where_clause_bts);

						#read student tables
						my $prep_stmt5 = $con->prepare("SELECT adm_no,table_name FROM adms WHERE $where_clause LIMIT $num_rows");
	
						if ($prep_stmt5) {

							my $rc = $prep_stmt5->execute(keys %recipients);
							if ($rc) {
								while ( my @rslts = $prep_stmt5->fetchrow_array() ) {
									$stud_lookup{$rslts[0]} = $rslts[1];
								}
							}
							else {
								print STDERR "Could not execute SELECT FROM student_rolls: ", $con->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare SELECT FROM student_rolls: ", $con->errstr, $/;
						}
					}

				}

				unless (keys %recipients) {
					last O;
				}

				#check if contacts.name has been requested
				if ( $msg_template =~ /<<contacts\.name>>/ ) {

					my %contact_names;

					my @where_clause_bts = ();

					foreach ( keys %recipients ) {
						push @where_clause_bts, "id=?";
					}

					my $where_clause = join(" OR ", @where_clause_bts);
					my $num_rows = scalar(@where_clause_bts);

					my $prep_stmt7 = $con->prepare("SELECT id,name FROM contacts WHERE $where_clause LIMIT $num_rows");
	
					if ($prep_stmt7) {
						my $rc = $prep_stmt7->execute(keys %recipients);
						if ($rc) {
							while ( my @rslts = $prep_stmt7->fetchrow_array() ) {
								$contact_names{$rslts[0]} = $rslts[1];
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM contacts: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM contacts: ", $con->errstr, $/;
					}

					#substitute <<contacts.name>> for the contact name found
					for my $recipient ( keys %recipients ) {
						my $name = "N/A";
						if (exists $contact_names{$recipient}) {
							$name = $contact_names{$recipient};
						}
						$recipients{$recipient} =~ s/<<contacts\.name>>/$name/g;
					}
				}

				#check if students.class_teacher has been requested
				if ($msg_template =~ /<<students\.class_teacher>>/) {

					#translate between table names and class name
					if (not keys %class_lookup) {

						my $prep_stmt4 = $con->prepare("SELECT table_name,class,start_year FROM student_rolls");
	
						if ($prep_stmt4) {
							my $rc = $prep_stmt4->execute();
							if ($rc) {

								while ( my @rslts = $prep_stmt4->fetchrow_array() ) {

									my $class = $rslts[1];
									my $yr = ( $current_yr - $rslts[2] ) + 1;

									$class =~ s/\d+/$yr/;
								
									$class_lookup{lc($class)} = { "table" => $rslts[0], "start_year" => $rslts[2] };
								}

							}
							else {
								print STDERR "Could not execute SELECT FROM student_rolls: ", $con->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare SELECT FROM student_rolls: ", $con->errstr, $/;
						}
					}


					my %class_to_teacher_lookup = ();

					my $prep_stmt2 = $con->prepare("SELECT id,value FROM vars WHERE id LIKE '1-class teacher%'");
	
					if ($prep_stmt2) {
						my $rc = $prep_stmt2->execute();
						if ($rc) {
							while ( my @rslts = $prep_stmt2->fetchrow_array() ) {

								my $id = $rslts[0];
								my $name = $rslts[1];

								if ($id =~ /^1-class\steacher\s([^\(]+)\((\d{4,})\)$/) {

									my $class = $1;
									my $year = $2;

									my $class_yr = 1;
									if ($class =~ /(\d+)/) {
										$class_yr = $1;
									}

									my $class_now = ($current_yr - $year) + $class_yr; 
									$class =~ s/\d+/$class_now/;

									if (exists $class_lookup{lc($class)}) {

										my $table = ${$class_lookup{lc($class)}}{"table"};

										$class_to_teacher_lookup{$table} = $name;
									}
								}
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM vars: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM vars: ", $con->errstr, $/;
					}

					for my $recipient (keys %recipients) {
						#don't want uninitialized values

						if (exists $stud_lookup{$recipient}) {

							my $class = $stud_lookup{$recipient};

							my $class_ta = "N/A";

							if ( exists $class_to_teacher_lookup{$class} ) {
								$class_ta = $class_to_teacher_lookup{$class};
							}

							$recipients{$recipient} =~ s/<<students\.class_teacher>>/$class_ta/g;
						}
					}
				}

				my @stud_cols = ();

				foreach ("adm", "s_name", "o_names", "marks_at_adm", "subjects", "clubs_societies", "sports_games", "responsibilities", "house_dorm") {
					#is this column referenced?
					if ($msg_template =~ /<<students\.$_>>/) {
						push @stud_cols, $_;
					}
				}

				if ( @stud_cols ) {

					my $adm_prepended = 0;
					#adm is essential
					if ($stud_cols[0] ne "adm") {
						unshift (@stud_cols, "adm");
						$adm_prepended++;
					}

					#what tables to read? 
					my %tables;
					for my $stud (keys %stud_lookup) {
						my $table = $stud_lookup{$stud};
						${$tables{$table}}{$stud}++;
					}

					my $cols_str = join(",", @stud_cols);
	
					for my $table (keys %tables) {

						my %data;

						my @studs_in_class = keys %{$tables{$table}};
						
						my @where_clause_bts = ();
						for my $stud_in_class (@studs_in_class) {
							push @where_clause_bts, "adm=?";
						}

						my $where_clause = join(" OR ", @where_clause_bts);
						my $num_rows = scalar(@studs_in_class);

						my $prep_stmt2 = $con->prepare("SELECT $cols_str FROM `$table` WHERE $where_clause LIMIT $num_rows");
	
						if ($prep_stmt2) {
							my $rc = $prep_stmt2->execute(@studs_in_class);
							if ($rc) {
								while ( my @rslts = $prep_stmt2->fetchrow_array() ) {

									$data{$rslts[0]} = {};
									for (my $i = 0; $i < @rslts; $i++) {
										${$data{$rslts[0]}}{$stud_cols[$i]} = $rslts[$i];
									}
								}

								my $start = 0;
								$start = 1 if ($adm_prepended);

								for ( my $j = 0; $j < @studs_in_class; $j++ ) {

									for (my $k = $start; $k < @stud_cols; $k++) {

										my $col_val = "N/A";
										if ( exists ${$data{$studs_in_class[$j]}}{$stud_cols[$k]} ) {
											$col_val = ${$data{$studs_in_class[$j]}}{$stud_cols[$k]};
										}

										$recipients{$studs_in_class[$j]} =~ s/<<students\.$stud_cols[$k]>>/$col_val/g;
									}
								}
							}
							else {
								print STDERR "Could not execute SELECT FROM vars: ", $con->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare SELECT FROM vars: ", $con->errstr, $/;
						}
					}
				}

				#check for TA cols;
				my @tas_cols = ();

				foreach ("id", "name", "subjects") {
					#is this column referenced?
					if ( $msg_template =~ /<<teachers\.$_>>/ ) {
						push @tas_cols, $_;
					}
				}

				if ( @tas_cols ) {

					my $id_prepended = 0;
					#id is essential
					if ($tas_cols[0] ne "id") {
						unshift (@tas_cols, "id");
						$id_prepended++;
					}

					my @where_clause_bts = ();
					foreach (keys %recipients) {
						push @where_clause_bts, "id=?";
					}

					my $where_clause = join(" OR ", @where_clause_bts);
					my $num_rows = scalar(@where_clause_bts);

					my $cols_str = join(",", @tas_cols);

					my %data = ();
					my $prep_stmt2 = $con->prepare("SELECT $cols_str FROM teachers WHERE $where_clause LIMIT $num_rows");
	
					if ($prep_stmt2) {

						my $rc = $prep_stmt2->execute(keys %recipients);
						if ($rc) {
							while ( my @rslts = $prep_stmt2->fetchrow_array() ) {

								$data{$rslts[0]} = {};
								for (my $i = 0; $i < @rslts; $i++) {
									${$data{$rslts[0]}}{$tas_cols[$i]} = $rslts[$i];
								}
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM teachers: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM teachers: ", $con->errstr, $/;
					}

					my $start = 0;
					$start = 1 if ($id_prepended);

					for my $recipient (keys %recipients) {

						for (my $k = $start; $k < @tas_cols; $k++) {

							my $col_val = "N/A";
							if ( exists ${$data{$recipient}}{$tas_cols[$k]} ) {
								if ($tas_cols[$k] eq "subjects") {

									#say English[1A(2016),2A(2015)];Kiswahili[3A(2014)]
									my $machine_class_subjs = ${$data{$recipient}}{$tas_cols[$k]};
			
									#now i have 
									#[0]: English[1A(2016),2A(2015)]
									#[1]: Kiswahili[3A(2014)]
									my @subj_groups = split/;/, $machine_class_subjs;
									my @reformd_subj_group = ();

									#take English[1A(2016),2A(2015)]
									J: for my $subj_group (@subj_groups) {

										my ($subj,$classes_str);
						
										if ($subj_group =~ /^([^\[]+)\[([^\]]+)\]$/) {
											#English
											my $subj = $1;
											#1A(2016),2A(2015)
											my $classes_str = $2;	
											#[0]: 1A(2016)
											#[1]: 2A(2015)
											my @classes_list = split/,/, $classes_str;
											my @reformd_classes_list = ();

											#take 1A(2016) 	
											for my $class (@classes_list) {	
												if ($class =~ /\((\d+)\)$/) {	
													my $grad_yr = $1;	

													my $class_dup = $class;
													$class_dup =~ s/\($grad_yr\)//;

													if ( $grad_yr >= $current_yr ) {

														my $class_yr = $yrs_study - ($grad_yr - $current_yr);
														$class_dup =~ s/\d+/$class_yr/;

														push @reformd_subj_group, "$subj($class_dup)";
														
													}
												}
											}
										}
									}

									$col_val = join(", ", @reformd_subj_group);
								}
								else {
									$col_val = ${$data{$recipient}}{$tas_cols[$k]};
								}
							}
							$recipients{$recipient} =~ s/<<teachers\.$tas_cols[$k]>>/$col_val/g;
						}
					}
				}


				if ( $msg_template =~ /<<teachers\.lessons>>/ ) {

					my (@selected_classes, %selected_days, %exception_days,%day_orgs,%machine_day_orgs,%lesson_assignments,%lesson_to_teachers) = (undef,undef,undef,undef,undef,undef, undef);
						
					my $prep_stmt_2 = $con->prepare("SELECT selected_classes, selected_days, exception_days, day_orgs, machine_day_orgs, lesson_assignments, lesson_to_teachers FROM timetables WHERE is_committed=1 ORDER BY id DESC LIMIT 1");

					if ($prep_stmt_2) {
						my $rc = $prep_stmt_2->execute();
						if ($rc) {
							while (my @rslts = $prep_stmt_2->fetchrow_array()) {
	
								@selected_classes = @{thaw($rslts[0])};
								%selected_days = %{thaw($rslts[1])};
								%exception_days = %{thaw($rslts[2])};
								%day_orgs = %{thaw($rslts[3])};
								%machine_day_orgs = %{thaw($rslts[4])};
								%lesson_assignments = %{thaw($rslts[5])};
								%lesson_to_teachers = %{thaw($rslts[6])};

							}
						}
						else {
							print STDERR "Could not execute SELECT FROM timetables", $prep_stmt_2->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM timetables", $prep_stmt_2->errstr, $/;
					}

					#translate between machine event ids
					#and human event descriptions
					my %event_lookup;
					my %day_short_forms = ("Monday" => "Mon", "Tuesday" => "Tue", "Wednesday" => "Wed", "Thursday" => "Thu", "Friday" => "Fri", "Saturday" => "Sat", "Sunday" => "Sun");

					for my $class (@selected_classes) {

						foreach my $day ( "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday" ) {

							next if ( not exists $selected_days{$day} );

							my $organization = 0;	

							if ( exists $exception_days{$day} ) {
								$organization = $exception_days{$day};	
							}
	
							my $start_lessons = ${$day_orgs{$organization}}{"start"};
							my ($hrs,$mins) = (0,0);
							my $colon = "";

							if ($start_lessons =~ /^(\d{1,2})(:?)(\d{1,2})$/) {
								$hrs   = $1;
								$mins  = $3;
								$colon = $2;
							}								

							for my $event ( sort {$a <=> $b} keys %{$machine_day_orgs{$organization}} ) {

								my $duration = ${${$machine_day_orgs{$organization}}{$event}}{"duration"};

								my $duration_mins = $duration % 60;
								my $duration_hrs = int($duration / 60);
							
								my $stop_hrs = $hrs + $duration_hrs; 
								my $stop_mins = $mins + $duration_mins;

								if ($stop_mins >= 60) {
									$stop_mins = $stop_mins - 60;
									$stop_hrs++;
								}
					
								($hrs,$mins,$stop_hrs,$stop_mins) = (sprintf("%02d", $hrs), sprintf("%02d", $mins), sprintf("%02d", $stop_hrs), sprintf("%02d", $stop_mins));

								my $time = "${hrs}${colon}${mins}-${stop_hrs}${colon}${stop_mins}";
			
								my $short_day = 
								$event_lookup{"${day}_${event}"}  = "$day($time)";

								$hrs  = $stop_hrs;
								$mins = $stop_mins;
							}

						}
					}

					my %subject_short_forms = ("english" => "Eng", "kiswahili" => "Kisw", "physics" => "Phy", "mathematics" => "Math", "chemistry" => "Chem", "biology" => "Bio", "agriculture" => "Agric", "geography" => "Geog", "computers" => "Comps", "history" => "Hist", "home science" => "H/Sci", "business studies" => "B/S");

					my %ta_lesson_assignments;

					for my $class (keys %lesson_assignments) {

						for my $day (keys %{$lesson_assignments{$class}}) {

							my $organization = 0;
					
							if ( exists $exception_days{$day} ) {
								$organization = $exception_days{$day};
							}

							for my $event ( keys %{${$lesson_assignments{$class}}{$day}} ) {

								#ignore the fixed events
								unless ( $machine_day_orgs{$organization}->{$event}->{"type"} == 1 ) {
									
									my @subjects = keys %{${${$lesson_assignments{$class}}{$day}}{$event}};

									for my $subj (@subjects) {
										my @tas = @{$lesson_to_teachers{lc("$subj($class)")}};
										for ( my $j = 0; $j < @tas; $j++ ) {
											if ( not exists $ta_lesson_assignments{$tas[$j]} ) {
												$ta_lesson_assignments{$tas[$j]} = {};
											}

											my $event_descr = $event_lookup{"${day}_${event}"};
											if ( exists $subject_short_forms{lc($subj)} ) {
												$subj = $subject_short_forms{lc($subj)};
											}
											${$ta_lesson_assignments{$tas[$j]}}{$event_descr} = "$subj($class)";
										}
									}
								}
							}
						}
					}

					for my $recipient (keys %recipients) {

						my $lessons = "N/A";
						
						if ( exists $ta_lesson_assignments{$recipient} ) {

							my @lessons = ();
							for my $event ( keys %{$ta_lesson_assignments{$recipient}} ) {
								push @lessons, "$event - " . ${$ta_lesson_assignments{$recipient}}{$event};
							}
							$lessons = join("\n", @lessons);
						}
						
						$recipients{$recipient} =~ s/<<teachers\.lessons>>/$lessons/g;
					}
				}

				#students results
				if ( $msg_template =~ /<<students\.results>>/ ) {

					#convert class->tables lookup to yr->tables lookup
					my %tables;
					for my $class (keys %class_lookup) {

						my $table = ${$class_lookup{$class}}{"table"};
						my $yr = ${$class_lookup{$class}}{"start_year"};

						${$tables{$yr}}{$table}++;
					}

					my %requested_tables;

					for my $stud ( keys %stud_lookup ) {

						my $tbl = $stud_lookup{$stud};
						$requested_tables{$tbl}++;

					}

					#chuck any unrepresented 
					for my $start_yr ( keys %tables ) {
	
						my @tables_arr = keys %{$tables{$start_yr}};
						
						my $repd = 0;

						foreach (@tables_arr) {
							if (exists $requested_tables{$_}) {
								$repd++;
								last;
							}
						}

						delete $tables{$start_yr} if (not $repd);
					}

					my %subject_short_forms = ("english" => "Eng", "kiswahili" => "Kisw", "physics" => "Phy", "mathematics" => "Math", "chemistry" => "Chem", "biology" => "Bio", "agriculture" => "Agric", "geography" => "Geog", "computers" => "Comps", "history" => "Hist", "home science" => "H/Sci", "business studies" => "B/S");

					for my $start_year ( keys %tables ) {

						
						my %class_sizes = ();
						my $yr_size = 0;

						my %stud_rolls;	
						my @tables_arr = keys %{$tables{$start_year}};

						my %stud_subjects = ();
						#need to reset for every class
						$yr_size = 0;

						my $stud_yr = ($exam_yr - $start_year) + 1;

						for my $table ( @tables_arr ) {
							
							my $prep_stmt5 = $con->prepare("SELECT adm,subjects FROM `$table`");

							if ($prep_stmt5) {

								my $rc = $prep_stmt5->execute();
								if ($rc) {
									while (my @rslts = $prep_stmt5->fetchrow_array()) {

										my @subjs = split/,/,$rslts[1];
										for my $subj (@subjs) {
											$stud_subjects{$rslts[0]}->{$subj}++;
										}

										$class_sizes{$table}++;
										$yr_size++;
									}
								}
								else {
									print STDERR "Could not execute SELECT FROM $table statement: ", $prep_stmt5->errstr, $/;
								}

							}
							else {
								print STDERR "Could not prepare SELECT FROM $table statement: ", $prep_stmt5->errstr, $/;
							}

						}

						my @where_clause_bts = ();

						foreach ( @tables_arr ) {
							push @where_clause_bts, "roll=?";
						}

						my $where_clause = join(' OR ', @where_clause_bts);

				      		my $prep_stmt4 = $con->prepare("SELECT table_name,roll,subject FROM marksheets WHERE exam_name=? AND ($where_clause)");

						if ($prep_stmt4) {

							my $rc = $prep_stmt4->execute($exam, @tables_arr);

							if ($rc) {

								while (my @rslts = $prep_stmt4->fetchrow_array()) {
									${$stud_rolls{$rslts[1]}}{$rslts[2]} = $rslts[0];
								}
							}
							else {
								print STDERR "Could not execute SELECT FROM marksheets statement: ", $prep_stmt4->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare SELECT FROM marksheets statement: ", $prep_stmt4->errstr, $/;
						}

						my %tables_hash;
						@tables_hash{@tables_arr} = @tables_arr;

						my %student_data = ();

						for my $stud ( keys %stud_lookup ) {

							my $tbl = $stud_lookup{$stud};
							next unless exists $tables_hash{$tbl};

							$student_data{$stud} = 
							{
							"points_total" => 0,
							"total" => 0,
							"subject_count" => 0,
							"points_avg" => -1,
							"avg" => -1,
							"mean_grade" => "-",
							"class_rank" => 1,
							"overall_rank" => 1,
							};


							#preset the values of subjects to N/A
							my @subjects_list = keys %{$stud_subjects{$stud}};

							unless ( $rank_partial ) {
								$student_data{$stud}->{"subject_count"} = scalar(@subjects_list);
							}

							foreach (@subjects_list) {
								${$student_data{$stud}}{"subject_$_"} = "N/A";
								${$student_data{$stud}}{"grade_subject_$_"} = "-";
							}
						}
	

						#read the marksheets in DB:-
						#for each marksheet, update student_data	
						#in the switch from F2-F3 the student's
						#'subjects' records are changed
						#RULE: assume subjects can be removed but not
						#added. Therefore, any missing records in the 
						#{"subjects"} field are N/A
						#any additional values however, are allowed
						
						for my $stud_roll (keys %stud_rolls) {
	
							for my $subject (keys %{$stud_rolls{$stud_roll}}) {
									
								my $marksheet =  ${$stud_rolls{$stud_roll}}{$subject};
									
								my $prep_stmt5 = $con->prepare("SELECT adm,marks FROM `$marksheet`");
								my %marksheet_data = ();

								if ($prep_stmt5) {
								
									my $rc = $prep_stmt5->execute();
									if ($rc) {
										while (my @rslts = $prep_stmt5->fetchrow_array()) {	
											$marksheet_data{$rslts[0]} = $rslts[1];
										}
									}
									else {
										print STDERR "Could not execute SELECT FROM $marksheet statement: ", $prep_stmt5->errstr, $/;
									}
								}
								else {
									print STDERR "Could not prepare SELECT FROM $marksheet statement: ", $prep_stmt5->errstr, $/;
								}

								for my $stud_adm (keys %marksheet_data) {
									
 									${$student_data{$stud_adm}}{"subject_$subject"} = $marksheet_data{$stud_adm};

									my $grade = get_grade($marksheet_data{$stud_adm});		
									${$student_data{$stud_adm}}{"grade_subject_$subject"} = $grade;
					
									if ( $rank_partial or not exists $stud_subjects{$stud_adm}->{$subject} ) {
										${$student_data{$stud_adm}}{"subject_count"}++;
									}

									my $points = $points{$grade};

									${$student_data{$stud_adm}}{"total"} += $marksheet_data{$stud_adm};
									${$student_data{$stud_adm}}{"points_total"} += $points;

									${$student_data{$stud_adm}}{"avg"} = ${$student_data{$stud_adm}}{"total"} / ${$student_data{$stud_adm}}{"subject_count"};
									${$student_data{$stud_adm}}{"points_avg"} = ${$student_data{$stud_adm}}{"points_total"} / ${$student_data{$stud_adm}}{"subject_count"};
									
									${$student_data{$stud_adm}}{"mean_grade"} = get_grade(${$student_data{$stud_adm}}{"avg"});
								
								}
							}
						}

						my %class_rank_cntr = ();

						foreach (keys %stud_rolls) {	
							$class_rank_cntr{$_} = 0;	
						}

						my $overall_cntr = 0;

						my $rank_by = "avg";
						if ( exists $rank_by_points{$stud_yr} ) {
							$rank_by = "points_avg";
						}

						for my $stud (sort { ${$student_data{$b}}{$rank_by} <=> ${$student_data{$a}}{$rank_by} } keys %student_data) {

							${$student_data{$stud}}{"overall_rank"} = ++$overall_cntr;
							my $class = $stud_lookup{$stud};

							${$student_data{$stud}}{"class_rank"} = ++$class_rank_cntr{$class};	
						}
	
						my $prev_rank = -1;
						my $prev_avg = -1;

						#deal with ties within class
						for my $stud_2 (sort { ${$student_data{$a}}{"overall_rank"} <=> ${$student_data{$b}}{"overall_rank"} } keys %student_data) {
							my $current_rank = ${$student_data{$stud_2}}{"overall_rank"};
							my $current_avg = ${$student_data{$stud_2}}{$rank_by};
		
							if ( $prev_avg == $current_avg ) {
								${$student_data{$stud_2}}{"overall_rank"} = $prev_rank;
							}
						
							$prev_rank = ${$student_data{$stud_2}}{"overall_rank"};
							$prev_avg  = $current_avg;
						}

						my %class_rank_cursor = ();

						foreach (keys %stud_rolls) {	
							$class_rank_cursor{$_} = {"prev_rank" => -1, "prev_avg" => -1};
						}

						for my $stud_3 (sort {${$student_data{$a}}{"overall_rank"} <=> ${$student_data{$b}}{"overall_rank"} } keys %student_data) {

							my $class = $stud_lookup{$stud_3};
				
							my $current_rank = ${$student_data{$stud_3}}{"class_rank"};
							my $current_avg = ${$student_data{$stud_3}}{$rank_by};
								
							if (${$class_rank_cursor{$class}}{"prev_avg"} == $current_avg) {
								${$student_data{$stud_3}}{"class_rank"} = ${$class_rank_cursor{$class}}{"prev_rank"};
							}
							
							${$class_rank_cursor{$class}}{"prev_rank"} = ${$student_data{$stud_3}}{"class_rank"};
							${$class_rank_cursor{$class}}{"prev_avg"}  = $current_avg;
						}

						
						for my $recipient (keys %recipients) {
							my $tbl = $stud_lookup{$recipient};
							#here be dragons--had a bug: wld replace
							#all '<<students.results>>' fields with 'N/A'
							#after the 1st class was processed.
							
							next unless (exists $tables_hash{$tbl});

							my $results = "N/A";

							if (exists $student_data{$recipient}) {

								my %data = %{$student_data{$recipient}};
								my $table = $stud_lookup{$recipient};

								my @subjects_results = ();

								for my $data_elem (sort {$a cmp $b} keys %data) {
									if ($data_elem =~ /^subject_(.+)/) {

										next if ($data_elem eq "subject_count");

										my $subj = $1;
										my $subj_short_form = $subj;

										if ( exists $subject_short_forms{lc($subj)} ) {

											$subj_short_form = $subject_short_forms{lc($subj)};

										}

										my $score = $data{$data_elem};
										my $grade = $data{"grade_subject_$subj"};
	
										push @subjects_results, "$subj_short_form: $score($grade)";
									}
								}

								my $results_str = join("  ", @subjects_results);

								$results_str .= ". Avg: " . sprintf("%.2f", $data{"avg"}) . "(" . $data{"mean_grade"} . ")"; 
								$results_str .= ". Class Pos: " . $data{"class_rank"}   . " of " . $class_sizes{$table};
								$results_str .= ". Overall Pos: " . $data{"overall_rank"} . " of " . $yr_size;
						
								$results = $results_str;
							}

							$recipients{$recipient} =~ s/<<students\.results>>/$results/g;

						}
					}
				}

				#process datasets
				for my $dataset ( keys %dataset_metadata ) {

					my %data = ();
					my $pry_key = $dataset_metadata{$dataset};

					my $lines = 0;

					open (my $f, "<$upload_dir/$dataset");

					while ( <$f> ) {

						chomp;
						

						$lines++;

						my $line = $_;

						my @cols = split/,/,$line;

						KK: for (my $i = 0; $i < (scalar(@cols) - 1); $i++) {
							#escaped
							if ( $cols[$i] =~ /(.*)\\$/ ) {

								my $non_escpd = $1;
								$cols[$i] = $non_escpd . "," . $cols[$i+1];

								splice(@cols, $i+1, 1);
								redo KK;
							}

							#assume that quotes will be employed around
							#an entire field
							#has it been opened?
							if ($cols[$i] =~ /^".+/) {
								#has it been closed? 
								unless ( $cols[$i] =~ /.+"$/ ) {
									#assume that the next column 
									#is a continuation of this one.
									#& that a comma was unduly pruned
									#between them
									$cols[$i] = $cols[$i] . "," . $cols[$i+1];
								splice (@cols, $i+1, 1);
									redo KK;
								}
							}
						}

						for (my $j = 0; $j < @cols; $j++) {
							if ($cols[$j] =~ /^"(.*)"$/) {
								$cols[$j] = $1; 
							}
						}

						if ($lines > 1) {
							$data{$cols[$pry_key]} = {};
							for ( my $k = 0; $k < @cols; $k++ ) {
								next if ($k == $pry_key);
								$data{$cols[$pry_key]}->{$k} = $cols[$k]; 
							}
						}
					}

					for my $recipient ( keys %recipients ) {

						if (exists $data{$recipient}) {

							my @known_fields = keys %{$data{$recipient}};

							for my $known_field (@known_fields) {

								if ( $recipients{$recipient} =~ /<<$dataset\.$known_field>>/ ) {
									$recipients{$recipient} =~ s/<<$dataset\.$known_field>>/$data{$recipient}->{$known_field}/g;
								}
							}
						}
						else {
							$recipients{$recipient} =~ s!<<$dataset\.\d+>>!N/A!g;
						}
					}
				}

				}

				my %contacts = ();

				my $prep_stmt8 = $con->prepare("SELECT id,phone_no FROM contacts");
	
				if ($prep_stmt8) {
					my $rc = $prep_stmt8->execute();
					if ($rc) {
						while ( my @rslts = $prep_stmt8->fetchrow_array() ) {
							$contacts{$rslts[0]} = $rslts[1];
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM contacts: ", $con->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM contacts: ", $con->errstr, $/;
				}

				if ( exists $auth_params{"commit"} ) {
	
					my $job_name = $session{"job_name"};
					my $modem = $session{"modem"};
					
					my $message_template = $session{"message_template"};

					my $message_validity = $session{"message_validity"};
			
					my $db_filter_type = "";
					if ( exists $session{"db_filter_type"} ) {
						$db_filter_type = $session{"db_filter_type"};
					}
				
					my $db_filter = "";
					if ( exists  $session{"db_filter"} ) {
 						$db_filter = $session{"db_filter"};
					}

					my $datasets = "";
					if ( exists $session{"datasets"} ) {
						$datasets = $session{"datasets"};
					}

					#create job with default values.
					my $prep_stmt2 = $con->prepare("INSERT INTO messaging_jobs VALUES (NULL,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL,0,NULL)");

					if ($prep_stmt2) {

						my $rc = $prep_stmt2->execute( $job_name, $modem,$message_template,$message_validity,$db_filter_type, $db_filter, $datasets );
						if ($rc) {
							$con->commit();
							#log create directory
							my @today = localtime;	
							my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
						
							open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

      	 						if ($log_f) {

       								@today = localtime;	
								my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
								flock ($log_f, LOCK_EX) or print STDERR "Could not log create messaging job for 1 due to flock error: $!$/";
								seek ($log_f, 0, SEEK_END);
				 
								print $log_f "1 CREATE MESSAGING JOB $job_name $time\n";
								flock ($log_f, LOCK_UN);
       								close $log_f;

       							}
							else {

								print STDERR "Could not log create messaging job for 1: $!\n";

							}
						}
						else {
							print STDERR "Could not execute INSERT INTO messaging_jobs: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare INSERT INTO messaging_jobs: ", $con->errstr, $/;
					}

					my $id = undef;

					my $prep_stmt3 = $con->prepare("SELECT id FROM messaging_jobs WHERE message_template=? ORDER BY id DESC LIMIT 1");

					if ($prep_stmt3) {

						my $rc = $prep_stmt3->execute($message_template);
						if ($rc) {
							while ( my @rslts = $prep_stmt3->fetchrow_array() ) {
								$id = $rslts[0];
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM messaging_jobs: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM messaging_jobs: ", $con->errstr, $/;
					}

					$feedback = qq!<span style="color: red">Could not start the messaging job.</span>!;

					if (defined $id) {

						#write to outbox
						my $prep_stmt3 = $con->prepare("INSERT INTO outbox VALUES(NULL,$id,?,?,0)");

						if ($prep_stmt3) {

							for my $recipient (keys %recipients) {

								if ( exists $contacts{$recipient} ) {

									my @phone_nos = split/,/, $contacts{$recipient};

									for my $phone_no (@phone_nos) {
										#I18n'd nums hav a + @ the start
										next unless ( $phone_no =~ /^\+?\d+$/ );

										#if I try catching these errors and I 
										#succeed, I'll crowd the error log. 

										my $rc = $prep_stmt3->execute($phone_no, $recipients{$recipient});
										
										unless ( $rc ) {
											print STDERR "Could not INSERT INTO outbox. Job: $id; Recipient: $recipient: ", $con->errstr, $/;
										}
									}
								}
							}
							$con->commit();
						}
						else {
							print STDERR "Could not prepare SELECT FROM messaging_jobs: ", $con->errstr, $/;
						}


						$feedback = qq!<span style="color: green">Starting messaging job.</span> Would you like to <a href="/cgi-bin/message.cgi?act=view_job&job=$id">view the running job</a>?!;

						#do a fork
						#withing the child call system("perl <path> id"), 
						#then exit
						#
						my $pid = fork;

						if (defined $pid) {
							#child
							if ($pid == 0) {

								use POSIX;

								close STDIN;
								close STDOUT;
								close STDERR;

								POSIX::setsid();

								exec "perl", "/usr/local/bin/spanj_sms.pl", $id;

								exit 0;

							}
							#parent--just $SIG{CHLD} = 'IGNORE'
							else {
								$SIG{CHLD} = 'IGNORE';
							}
						}
					}

					$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Send Messages - Create new Job</title>
</head>

<body>
$header
$feedback
*;

					
				}
				else {
					my $msgs = "";
					unless (keys %recipients) {
					
						$msgs = qq!<em>There're no records in the DB!;
						if (exists $session{"db_filter"}) {
							$msgs .= " matching the filter parameters you entered.";
						}
						else {
							$msgs .= ".</em>";
						}
					}
					else {
	
						$msgs = qq!
<p>If the messages listed below appear correct, click 'Send' to begin sending them out.
<p>NOTE: Any message that has been greyed out will not be sent because there are not contacts associated with it.
<p>

<FORM method="POST" action="/cgi-bin/message.cgi?act=create_job&create_stage=8">

<INPUT type="hidden" name="confirm_code" value="$session{"confirm_code"}">
<INPUT type="hidden" name="commit" value="1">
<INPUT type="submit" name="send" value="Send">

</FORM>
<p>
<TABLE border="1" style="width: 30em">
<THEAD><TH>Recipient<TH>Message</THEAD>
<TBODY>
!;

						
						for my $recipient (keys %recipients) {

							my $style = "";
							unless (exists $contacts{$recipient}) {
								$style = qq! style="color: gray" !;
							}

							my $msg = $recipients{$recipient};	
							$msgs .= "<TR$style><TD>$recipient<TD>" . htmlspecialchars($msg);
							$msg =~ s/\n/<br>/g;

						}

						$msgs .= "</TBODY></TABLE>";
					}

					$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Send Messages - Create new Job</title>
</head>

<body>
$header

$msgs

</body>

</html>
*;
				}

				
			}
			else {
				$feedback =  qq!<span style="color: red">This job does not appear properly initialized.</span>. Please restart this process.!;
				$create_stage = 1;
			}
		}

		if ($create_stage == 5) {
			if ( exists $session{"job_name"} and exists $session{"modem"} and exists $session{"message_template"} ) {

				my $class_filtered = 1;
				my $limit_by = "classes";

				if ( $session{"db_filter_type"} eq "teachers" ) {
					$class_filtered = 0;
					$limit_by = "subject/class teachers"
				}


				my (@subjects, @classes);

				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				my $prep_stmt2 = $con->prepare("SELECT id,value FROM vars WHERE id='1-subjects' OR id='1-classes'");
	
				if ($prep_stmt2) {
					my $rc = $prep_stmt2->execute();
					if ($rc) {
						while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
							if ($rslts[0] eq "1-subjects") {
								@subjects = split/,/, htmlspecialchars($rslts[1]);
							}
							elsif ($rslts[0] eq "1-classes") {
								@classes = split/,/, htmlspecialchars($rslts[1]);
							}
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM vars: ", $con->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM vars: ", $con->errstr, $/;
				}

				my $filter_select = "";

				if ( $class_filtered ) {
					$filter_select = qq!<UL style="list-style-type: none">!; 
					
					for my $class ( @classes ) {
						$filter_select .= qq!<LI><INPUT type="checkbox" name="filter_class_$class" value="$class" checked>&nbsp;&nbsp;$class!;
					}

					$filter_select .= "</UL>";
				}
				else {
					
					my $classes_list = "";
					for my $class ( @classes ) {
						$classes_list .= qq!<INPUT type="checkbox" name="filter_teachers_class_$class" value="$class" checked>&nbsp;&nbsp;$class<BR>!;	
					}

					my $subjects_list = "";
					for my $subject ( @subjects ) {
						$subjects_list .= qq!<INPUT type="checkbox" name="filter_teachers_subject_$subject" value="$subject" checked>&nbsp;&nbsp;$subject<BR>!;	
					}

					$filter_select = 
qq!
<TABLE>
<THEAD><TH>Classes<TH>Subjects</THEAD>
<TBODY>
<TR><TD style="border-right: solid">$classes_list<TD>$subjects_list
</TBODY>
</TABLE>
!;
				}

				my $conf_code = $session{"confirm_code"};

				$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Send Messages - Create new Job</title>
</head>

<body>
$header

<h4>Step 3 - Specify Recipients</h4>
<p>Which $limit_by do you want to receive this message:

<FORM method="POST" action="/cgi-bin/message.cgi?act=create_job&create_stage=6">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
$filter_select
<P><INPUT type="submit" name="save" value="Save">
</FORM>

</body>

</html>
*;
			}
			else {
				$feedback =  qq!<span style="color: red">This job does not appear properly initialized.</span>. Please restart this process.!;
				$create_stage = 1;
			}
		}
		if ($create_stage == 3) {

			if (exists $session{"job_name"} and exists $session{"modem"}) {

				my $fields_selection = "";

				if (exists $session{"datasets"}) {

					#I don't do linear searches anymore
					#I'm more into wasting memory and CPU cycles now.
					my @datasets = split/,/, $session{"datasets"};

					my %datasets;
					@datasets{@datasets} = @datasets;
					
					$fields_selection = 
qq!
<p>
<TABLE border="1">
<THEAD>
<TH>Field ID<TH>Field Name<TH>Dataset
</THEAD>
<TR><TD><a href="javascript:add_field('contacts.name')">contacts.name</a><TD>Contact's Name<TD>Contacts' DB
<TR><TD><a href="javascript:add_field('students.exam_name')">students.exam_name</a><TD>Current Exam<TD>Students' DB
!;

					my ($studs_linked, $tas_linked) = (0,0);

					#add Students' DB fields
					if ( exists $datasets{"students"} ) {
						#adm
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.adm')">students.adm</a><TD>Student's Admission Number<TD>Students' DB!;
						#s_name
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.s_name')">students.s_name</a><TD>Student's Surname<TD>Students' DB!;
						#o_names
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.o_names')">students.o_names</a><TD>Student's Other Names<TD>Students' DB!;
						#marks at admission
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.marks_at_adm')">students.marks_at_adm</a><TD>Student's Marks at Admission<TD>Students' DB!;
						#subjects
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.subjects')">students.subjects</a><TD>Student's Subjects<TD>Students' DB!;
						#clubs/societies
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.clubs_societies')">students.clubs_societies</a><TD>Student's Clubs/Societies<TD>Students' DB!;
						#sports/games
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.sports_games')">students.sports_games</a><TD>Student's Sports/Games<TD>Students' DB!;
						#responsibilities
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.responsibilities')">students.responsibilities</a><TD>Student's Responsibilities<TD>Students' DB!;
						#house/dorm
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.house_dorm')">students.house_dorm</a><TD>Student's House/Dorm<TD>Students' DB!;
						#results
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.results')">students.results</a><TD>Student's Results for the Current Exam<TD>Students' DB!;
						#class teacher
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.class_teacher')">students.class_teacher</a><TD>Student's Class Teacher<TD>Students' DB!;
						$studs_linked++;

						delete $datasets{"students"};
					}

					#having both students and teachers in the same 
					#template is rather pointless since they have no
					#overlapping field names.
					elsif ( exists $datasets{"teachers"} ) {
						#id
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('teachers.id')">teachers.id</a><TD>Teacher's Unique ID in the DB<TD>Teachers' DB!;
						#name
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('teachers.name')">teachers.name</a><TD>Teacher's Name<TD>Teachers' DB!;
						#subjects
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('teachers.subjects')">teachers.subjects</a><TD>Subjects Taught by the Teacher<TD>Teachers' DB!;
						#lessons
						$fields_selection .= qq!<TR><TD><a href="javascript:add_field('teachers.lessons')">teachers.lessons</a><TD>Teacher's Lessons as Assigned in the Timetable<TD>Teachers' DB!;

						$tas_linked++;
			
						delete $datasets{"teachers"};
					}

					#are there any user-uploaded datasets? 
					if (keys %datasets) {
						
						$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

						my $prep_stmt2 = $con->prepare("SELECT filename,name,link_to,header FROM datasets WHERE id=?");

						if ($prep_stmt2) {

							for my $dataset (keys %datasets) {

								my $rc = $prep_stmt2->execute($dataset);

								if ($rc) {
									while ( my @rslts = $prep_stmt2->fetchrow_array() ) {

										#checkif the studs DB is auto-linked
										if ( $rslts[2] eq "students" and not $studs_linked ) {
											#adm
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.adm')">students.adm</a><TD>Student's Admission Number<TD>Students' DB!;
											#s_name
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.s_name')">students.s_name</a><TD>Student's Surname<TD>Students' DB!;
											#o_names
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.o_names')">students.o_names</a><TD>Student's Other Names<TD>Students' DB!;
											#marks at admission
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.marks_at_adm')">students.marks_at_adm</a><TD>Student's Marks at Admission<TD>Students' DB!;
											#subjects
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.subjects')">students.subjects</a><TD>Student's Subjects<TD>Students' DB!;
											#clubs/societies
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.clubs_societies')">students.clubs_societies</a><TD>Student's Clubs/Societies<TD>Students' DB!;
											#sports/games
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.sports_games')">students.sports_games</a><TD>Student's Sports/Games<TD>Students' DB!;
											#responsibilities
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.responsibilities')">students.responsibilities</a><TD>Student's Responsibilities<TD>Students' DB!;
											#house/dorm
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.house_dorm')">students.house_dorm</a><TD>Student's House/Dorm<TD>Students' DB!;
											#results
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('students.results')">students.results</a><TD>Student's Results for the Current Exam<TD>Students' DB!;
											$studs_linked++;
										}

										elsif ( $rslts[2] eq "teachers" and not $studs_linked and not $tas_linked ) {
											#id
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('teachers.id')">teachers.id</a><TD>Teacher's Unique ID in the DB<TD>Teachers' DB!;
											#name
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('teachers.name')">teachers.name</a><TD>Teacher's Name<TD>Teachers' DB!;
											#subjects
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('teachers.subjects')">teachers.subjects</a><TD>Subjects Taught by the Teacher<TD>Teachers' DB!;
											#lessons
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('teachers.lessons')">teachers.lessons</a><TD>Teacher's Lessons<TD>Teachers' DB!;

											$tas_linked++;
										}

										my $src = htmlspecialchars("$rslts[1]\[$rslts[0]\]");
										my @headers = split/\$#\$#\$/, $rslts[3];

										for ( my $i = 0; $i < @headers; $i++ ) {

											my $col_name = htmlspecialchars($headers[$i]);
											$fields_selection .= qq!<TR><TD><a href="javascript:add_field('$dataset.$i')">$dataset.$i</a><TD>$col_name<TD>$src!;

										}
									}
								}

								else {
									print STDERR "Could not execute SELECT FROM datasets: ", $con->errstr, $/;
								}
							}
						}
						else {
							print STDERR "Could not prepare SELECT FROM datasets: ", $con->errstr, $/;
						}

					}
					$fields_selection .= "</TBODY></TABLE>";

				}

				#did not reacreate this session var to
				#allow this to be a continuation of the 
				#previous step.
				my $conf_code = $session{"confirm_code"}; 
	
				$content = 
qq*
<!DOCTYPE html>
<html lang="en">

<head>

<SCRIPT type="text/javascript">

function add_field(field) {
	msg_template.focus();

	var current_content = document.getElementById("msg_template").value;

	var insert_pt = current_content.length;

	if (msg_template.selectionStart) {
		insert_pt = msg_template.selectionStart;
	}

	var before = current_content.substr(0, insert_pt);
	var after = current_content.substr(insert_pt);

	var new_content = before + "<<" + field + ">> " + after;

	document.getElementById("msg_template").value = new_content;
}

</SCRIPT>

<title>Messenger - Send Messages - Create new Job</title>

</head>

<body>
$header

<h4>Step 2 - Compose Message Template</h4>
<p>A template defines the message to be sent out. Unlike a plain message, however, a template allows you to create a <span style="font-weight: bold">customized message</span> for each recipient. This is achieved through the inclusion of <span style="font-weight: bold">'fields'</span> from any selected dataset(s). You can add a field to the template by <span style="font-weight: bold">clicking it</span>. 

<FORM method="POST" action="/cgi-bin/message.cgi?act=create_job&create_stage=4">

<INPUT type="hidden" name="confirm_code" value="$conf_code">

<TABLE>

<TR><TD><LABEL for="expiry" title="How long to wait before delivery fails">Expires in</LABEL><TD>

<SELECT name="expiry" title="How long to wait before delivery fails">

<OPTION value="60">1 hour</OPTION>
<OPTION value="180">3 hours</OPTION>
<OPTION value="360">6 hours</OPTION>
<OPTION selected value="720">12 hours</OPTION>
<OPTION value="1440">1 day</OPTION>
<OPTION value="2880">2 days</OPTION>

</SELECT>
<TR>
<TD><LABEL for="message_template">Message Template</LABEL>
<TD>
<TEXTAREA name="message_template" id="msg_template" cols="50" rows="8"></TEXTAREA>
</TABLE>

$fields_selection

<TABLE>
<TR>
<TD><INPUT type="submit" name="save" value="Save Template">
</TABLE>
</body>
</html>
*;

			}
			else {
				$feedback =  qq!<span style="color: red">This job does not appear initialized.</span>. Please provide a basic description of this job first.!;
				$create_stage = 1;
			}
		}

		#user gives a name,modem, for the job
		if ($create_stage == 1) {

			$session{"job_name"} = "";
			$session{"modem"} = "";
			$session{"modem_path"} = "";
			$session{"datasets"} = "";
			$session{"message_template"} = "";
			$session{"message_validity"} = "";
			$session{"db_filter_type"} = "";
			$session{"db_filter"} = "";

			my @current_job_names = ();

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my $prep_stmt2 = $con->prepare("SELECT DISTINCT name FROM messaging_jobs");

			if ($prep_stmt2) {
				my $rc = $prep_stmt2->execute();
				if ($rc) {
					while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
						my $job_name = htmlspecialchars($rslts[0]);
						push @current_job_names, qq!"$job_name"!;
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM messaging_jobs: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM messaging_jobs: ", $con->errstr, $/;
			}

			my %modems = ();

			my $prep_stmt3 = $con->prepare("SELECT id,imei,description FROM modems WHERE enabled=1");

			if ($prep_stmt3) {

				my $rc = $prep_stmt3->execute();

				if ($rc) {
					while ( my @rslts = $prep_stmt3->fetchrow_array() ) {
						$modems{$rslts[0]} = htmlspecialchars("$rslts[2]($rslts[1])"); 
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
				}

			}
			else {
				print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr, $/;
			}

			my $num_modems = scalar(keys %modems);

			if ($num_modems > 0) {
				
				my $conf_code = gen_token();
				$session{"confirm_code"} = $conf_code;

				my $job_names_js_str = '[' . join(", ", @current_job_names) . ']';

				my $modem_selection = "";
				
				#only 1 modem to choose from
				#use readonly textfield
				if ($num_modems == 1) {

					my $modem_id = (keys %modems)[0];
					my $modem_descr = (values %modems)[0];

					$modem_selection = 
qq!
<INPUT type="text" value="$modem_descr" name="modem_description" size="30" disabled>
<INPUT type="hidden" name="modem" value="$modem_id">
!;
				}

				#show 'SELECT' menu
				else {

					$modem_selection = qq!<SELECT name="modem" size="2">!;

					for my $modem (keys %modems) {
						$modem_selection .= qq!<OPTION value="$modem">$modems{$modem}</OPTION>!;
					}

					$modem_selection .= "</SELECT>";
				}

				#datasets
				my %datasets = ();
				my $prep_stmt4 = $con->prepare("SELECT id,name FROM datasets");

				if ($prep_stmt4) {

					my $rc = $prep_stmt4->execute();

					if ($rc) {

						while ( my @rslts = $prep_stmt4->fetchrow_array() ) {
							$datasets{$rslts[0]} = htmlspecialchars($rslts[1]);
						}
					}

					else {
						print STDERR "Could not execute SELECT FROM datasets: ", $con->errstr, $/;
					}

				}
				else {
					print STDERR "Could not prepare SELECT FROM datasets: ", $con->errstr, $/;
				}

				my $dataset_selection =
qq!
<SELECT name="datasets" multiple size="4">
<OPTION value="students">Students' DB</OPTION>
<OPTION value="teachers">Teachers' DB</OPTION>
!;
				for my $dataset ( sort {$b <=> $a} keys %datasets ) {
					$dataset_selection .= qq!<OPTION value="$dataset">$datasets{$dataset}</OPTION>!;
				}

				$dataset_selection .= "</SELECT>";

				$content = 
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Messenger - Send Messages - Create new Job</title>

<SCRIPT type="text/javascript">

var current_jobs = $job_names_js_str;

function job_name_changed() {

	var requested_name = document.getElementById("job_name").value;

	if (requested_name.length > 0) {

		var collision = false;

		for ( var i = 0; i < current_jobs.length; i++ ) {
			if ( current_jobs[i] == requested_name ) {
				collision = true;
				break;
			}
		}
		if (collision) {
			document.getElementById("create").disabled = 1;
			document.getElementById("job_name_error_asterisk").innerHTML = "\*";
			document.getElementById("job_name_error").innerHTML = "A job with that name already exists.";
		}
		else {
			document.getElementById("create").disabled = 0;
			document.getElementById("job_name_error_asterisk").innerHTML = "";
			document.getElementById("job_name_error").innerHTML = "";
		}
	}
	else {
		document.getElementById("create").disabled = 1;
		document.getElementById("job_name_error_asterisk").innerHTML = "";
		document.getElementById("job_name_error").innerHTML = "";
	}
}

function disable_submit() {
	document.getElementById("create").disabled = 1;
}

</SCRIPT>

</head>

<body onload="disable_submit()">
$header
$feedback
<h4>Step 1 - Messaging Job Description</h4>

<p>Specify a name, modem and (optionally) any datasets you would like to use in the messaging job you wish to create. This name should be <em>unique</em> and as <em>descriptive</em> as possible.

<FORM method="POST" action="/cgi-bin/message.cgi?act=create_job&create_stage=2">

<INPUT type="hidden" name="confirm_code" value="$conf_code">

<TABLE border="0">

<TR>
<TD><LABEL for="job_name">Job Name</LABEL>

<TD><span style="color: red" id="job_name_error_asterisk"></span><INPUT type="text" name="job_name" id="job_name" value="" size="32" maxlength="64" onmousemove="job_name_changed()" onkeyup="job_name_changed()">

<TR>
<TD colspan="2" style="color: red">
<span id="job_name_error"></span>

<TR>
<TD><LABEL for="modem">Modem</LABEL>
<TD>$modem_selection

<TR>
<TD><LABEL for="datasets">Dataset</LABEL>
<TD>$dataset_selection

<TR>
<TD colspan="2"><INPUT type="submit" name="create" value="Create Job" id="create">

</TABLE>

</FORM>

</body>
</html>
*;

			}
			else {
				$content = 
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Messenger - Send Messages - Create new Job</title>
</head>

<body>

<p><SPAN style="color: red">Cannot proceed with messaging job creation: no modem detected.</SPAN> Connected modems are usually automatically detected by the system. If you have not connected any modem, please do. If you already have one connected, ensure it has a SIM attached and it's working properly.

</body>

</html>
*;
			}
		}	
	}

	elsif ( defined $act and $act eq "suspend_job" ) {
		if (defined $job) {

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my ($name,$pid) = (undef, undef);

			#get pid of jobs to suspend before deleting them 
			my $prep_stmt8 = $con->prepare("SELECT name,pid FROM messaging_jobs WHERE id=? LIMIT 1");

			if ($prep_stmt8) {
				my $rc = $prep_stmt8->execute($job);
				if ($rc) {
				while ( my @rslts = $prep_stmt8->fetchrow_array() ) {
						$name = $rslts[0];
						$pid = $rslts[1];
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM messaging_jobs: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM messaging_jobs: ", $con->errstr, $/;
			}

			#is there such a job
			if (defined $pid) {

				#update messaging jobs--set instructions to 2 (suspend)
				my $prep_stmt9 = $con->prepare("UPDATE messaging_jobs SET instructions=2 WHERE id=? LIMIT 1");
							
				my $success = 0;

				if ($prep_stmt9) {
					my $rc = $prep_stmt9->execute($job);

					if ($rc) {
						$success++;
					}
					else {						
						print STDERR "Could not execute UPDATE messaging_jobs: ", $con->errstr, $/;
					}
				
					$con->commit();
				}

				else {
					print STDERR "Could not prepare UPDATE messaging_jobs: ", $con->errstr, $/;
				}

		
				#could set instructions to 2	
				if ($success) {

					my $killed = kill 2, $pid;
					if ($killed) {	
								
						#log job suspends
						my @today = localtime;	
						my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
							
						open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

						if ($log_f) {

       							@today = localtime;	
							my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
							flock ($log_f, LOCK_EX) or print STDERR "Could not log suspend messaging job for 1 due to flock error: $!$/";
							seek ($log_f, 0, SEEK_END);
										
							print $log_f "1 SUSPEND MESSAGING JOB $name $time\n";
						

							flock ($log_f, LOCK_UN);
       							close $log_f;

		       				}
						else {
							print STDERR "Could not log suspend messaging job for 1: $!\n";
						}	
					}
					else {
						$feedback = qq!<p><span style="color: red">Could not signal the messaging job.</span>!;
						undef $act;
					}

					$act = "view_job";
				}
				else {
					$feedback = qq!<p><span style="color: red">Could not suspend the messaging job.</span>!;
					undef $act;
				}
			}
			else {
				$feedback = qq!<p><span style="color: red">The job specified does not exist.</span>!;
				undef $act;
			}			
		}
		else {
			$feedback = qq!<p><span style="color: red">No job specified.</span>!;
			undef $act;
		}
	}

	
	elsif ( defined $act and $act eq "refresh" ) {

		my $content = "";

		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});


		my @to_update = ();

		my $prep_stmt3 = $con->prepare("SELECT id,number_messages,number_delivered,last_activity FROM messaging_jobs WHERE instructions=1");

		if ($prep_stmt3) {
			my $rc = $prep_stmt3->execute();
			if ($rc) {

				while ( my @rslts = $prep_stmt3->fetchrow_array() ) {
					
					my $last_activity = custom_time($rslts[3]);

					#if done, display last activity as a date
					#because no updates expected.
					if ($rslts[2] >= $rslts[1]) {
						my @time_bts = localtime($rslts[3]);
						$last_activity = sprintf ("%02d/%02d/%d %02d:%02d:%02d", $time_bts[3], ($time_bts[4] + 1), ($time_bts[5] + 1900),  $time_bts[2], $time_bts[1], $time_bts[0]);
					}

					$content .= qq!$rslts[0]#$rslts[2]#$last_activity\$!;

					push @to_update, $rslts[0];

				}

			}
			else {
				print STDERR "Could not execute SELECT FROM messaging_jobs: ", $con->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM messaging_jobs: ", $con->errstr, $/;
		}

		if (@to_update) {
			my @where_clause_bts = ();
		
			foreach (@to_update) {
				push @where_clause_bts, "id=?";
			}
			my $where_clause = join(' OR ', @where_clause_bts);

			my $prep_stmt4 = $con->prepare("UPDATE messaging_jobs SET instructions=0 WHERE instructions=1 AND ($where_clause)");

			if ($prep_stmt4) {
				my $rc = $prep_stmt4->execute(@to_update);
				if ($rc) {
					$con->commit();
				}
				else {
					print STDERR "Could not execute UPDATE messaging_jobs: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare UPDATE messaging_jobs: ", $con->errstr, $/;
			}
		}

		print "Status: 200 OK\r\n";
		print "Content-Type: text/plain; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		print "\r\n";
		print $content;

		$con->disconnect();
		exit 0;
	}

	elsif  (defined $act and $act eq "refresh_job") {
		if ( defined $job ) {

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my ($number_messages, $number_delivered, $last_activity, $instructions, $recent_activity) = (undef, undef, undef, undef, undef);

			my $prep_stmt1 = $con->prepare("SELECT number_messages,number_delivered,last_activity,instructions,recent_activity FROM messaging_jobs WHERE id=? LIMIT 1");

			if ($prep_stmt1) {
				my $rc = $prep_stmt1->execute($job);
				if ($rc) {
					while ( my @rslts = $prep_stmt1->fetchrow_array() ) {
						$number_messages = $rslts[0];
						$number_delivered = $rslts[1];
						$last_activity = $rslts[2];
						$instructions = $rslts[3];
						$recent_activity = $rslts[4];
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM messaging_jobs: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM messaging_jobs: ", $con->errstr, $/;
			}

			#there's such an instruction
			if ( defined $instructions ) {
				#there're some updates
				if ( $instructions == 1 ) {

					#get per min, estimate remaining
					my ($min,$max,$sent) = (0,0,0);

					my $prep_stmt3 = $con->prepare("SELECT min(sent),max(sent),count(message_id) FROM outbox WHERE messaging_job=? AND sent > 0 LIMIT 1");
			
					if ($prep_stmt3) {

						my $rc = $prep_stmt3->execute($job);
						if ($rc) {
							while ( my @rslts = $prep_stmt3->fetchrow_array() ) {
								$min  = $rslts[0];
								$max  = $rslts[1];
								$sent = $rslts[2];
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
					}

					my $content = "";

					#some msgs have been sent
					if ($min and $max) {

						my $rate = sprintf("%.1f", ( 60 / ( ($max - $min) / $sent )));
						my $remaining_time = 0;
						if ($rate > 0) {
							$remaining_time = sprintf( "%.1f", ($number_messages - $number_delivered) / $rate );
						}

						#assuming running
						my $status = 1;
						#check if done
						if ($number_delivered >= $number_messages) {
							$status = 2; 
						}
						#check if defunct
						#last activity was more than 30 secs ago
						elsif ( ($last_activity + 30) < time ) {
							$status = 0;
						}

						$content = qq!$rate,$remaining_time,$status\n$recent_activity!;
					}

					print "Status: 200 OK\r\n";
					print "Content-Type: text/plain; charset=UTF-8\r\n";

					my $len = length($content);
					print "Content-Length: $len\r\n";

					print "\r\n";
					print $content;

					my $prep_stmt4 = $con->prepare("UPDATE messaging_jobs SET instructions=0 WHERE id=? LIMIT 1");
			
					if ($prep_stmt4) {

						my $rc = $prep_stmt4->execute( $job );

						if ($rc) {
							$con->commit();
						}
						else {
							print STDERR "Could not execute UPDATE messaging_jobs: ", $con->errstr, $/;
						}
					}

					else {
						print STDERR "Could not prepare UPDATE messaging_jobs: ", $con->errstr,$/;
					}
					$con->disconnect();
					exit 0;
				}
			}
			else {
				$feedback = qq!<p><span style="color: red">The job specified does not exist.</span>!;
				undef $act;
			}
		}
		else {
			$feedback = qq!<p><span style="color: red">No job specified.</span>!;
			undef $act;
		}
	}

	elsif  (defined $act and $act eq "refresh_inbox") {
		if (defined $modem) {

			my ($imei,$description,$enabled) = (undef, undef, 0);

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my $prep_stmt6 = $con->prepare("SELECT imei,description,enabled FROM modems WHERE id=? LIMIT 1");
			
			if ($prep_stmt6) {
				my $rc = $prep_stmt6->execute($modem);

				if ($rc) {
					while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
						$imei = $rslts[0];
						$description = $rslts[1];
						$enabled = $rslts[2]; 
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
			}

			if (defined $imei and $enabled) {

				my $content = "";

				my $num_new_msgs = 0;

				my $prep_stmt4 = $con->prepare("SELECT COUNT(message_id) FROM inbox WHERE modem=? AND message_read=0 LIMIT 1");
	
				if ( $prep_stmt4 ) {

					my $rc = $prep_stmt4->execute($modem);
					if ($rc) {
						while ( my @rslts = $prep_stmt4->fetchrow_array() ) {
							$num_new_msgs = $rslts[0];
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr, $/;
				}

				if ($num_new_msgs) {

					my $prep_stmt6 = $con->prepare("UPDATE inbox SET message_read=1 WHERE modem=? AND message_read=0");

					if ($prep_stmt6) {
						my $rc = $prep_stmt6->execute($modem);
						if ($rc) {
							$con->commit();
						}
						else {
							print STDERR "Could not execute UPDATE inbox: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare UPDATE inbox: ", $con->errstr, $/;
					}
				}
				
				if ( $num_new_msgs ) {
					$content = qq!$num_new_msgs!;
				}

				print "Status: 200 OK\r\n";
				print "Content-Type: text/plain; charset=UTF-8\r\n";

				my $len = length($content);
				print "Content-Length: $len\r\n";
	
				print "\r\n";
				print $content;

				$con->disconnect();
				exit 0;
			}

			#no such modem
			else {
				$feedback = qq!<p><span style="color: red">The modem selected does not exist.</span>!;
				undef $act;
			}
		}

		else {
			$feedback = qq!<p><span style="color: red">No modem selected.</span>!;
			undef $act;
		}
	}

	elsif ( defined $act and $act eq "refresh_modem" ) {

		if (defined $modem) {

			my ($imei,$description,$enabled) = (undef, undef, 0);

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my $prep_stmt6 = $con->prepare("SELECT imei,description,enabled FROM modems WHERE id=? LIMIT 1");
			
			if ($prep_stmt6) {
				my $rc = $prep_stmt6->execute($modem);

				if ($rc) {
					while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
						$imei = $rslts[0];
						$description = $rslts[1];
						$enabled = $rslts[2]; 
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
			}

			if (defined $imei and $enabled) {

				my $content = "";
 	
				my ($signal_quality,$access_tech, $status, $service_provider,$updated) = (undef, undef, undef, undef,0);

				my $prep_stmt3 = $con->prepare("SELECT signal_quality,access_tech,status,service_provider,updated FROM modems WHERE id=? LIMIT 1");

				if ($prep_stmt3) {
					my $rc = $prep_stmt3->execute($modem);
					if ($rc) {	
						while ( my @rslts = $prep_stmt3->fetchrow_array() ) {

							$signal_quality = $rslts[0];
							$access_tech = $rslts[1];
							$status = $rslts[2];
							$service_provider = htmlspecialchars($rslts[3]);
							$updated = $rslts[4];
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr, $/;
				}

				my $num_new_msgs = 0;

				my $prep_stmt4 = $con->prepare("SELECT COUNT(message_id) FROM inbox WHERE modem=? AND message_read=0 LIMIT 1");
	
				if ( $prep_stmt4 ) {

					my $rc = $prep_stmt4->execute($modem);
					if ($rc) {
						while ( my @rslts = $prep_stmt4->fetchrow_array() ) {
							$num_new_msgs = $rslts[0];
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr, $/;
				}

				if ($updated) {
	
					my $prep_stmt5 = $con->prepare("UPDATE modems SET updated=0 WHERE id=?");
	
					if ($prep_stmt5) {
						my $rc = $prep_stmt5->execute($modem);
						if ($rc) {
							$con->commit();
						}
						else {	
							print STDERR "Could not execute UPDATE modems: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare UPDATE modems: ", $con->errstr, $/;
					}
				}

				if ($num_new_msgs) {

					my $prep_stmt6 = $con->prepare("UPDATE inbox SET message_read=1 WHERE modem=? AND message_read=0");

					if ($prep_stmt6) {
						my $rc = $prep_stmt6->execute($modem);
						if ($rc) {
							$con->commit();
						}
						else {
							print STDERR "Could not execute UPDATE inbox: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare UPDATE inbox: ", $con->errstr, $/;
					}
				}
	
				#some changes have happened
				if ( $updated or $num_new_msgs ) {
					$content = qq!$signal_quality#$access_tech#$status#$service_provider#$num_new_msgs!;
				}

				print "Status: 200 OK\r\n";
				print "Content-Type: text/plain; charset=UTF-8\r\n";

				my $len = length($content);
				print "Content-Length: $len\r\n";
	
				print "\r\n";
				print $content;

				$con->disconnect();
				exit 0;
			}
			#no such modem
			else {
				$feedback = qq!<p><span style="color: red">The modem selected does not exist.</span>!;
				undef $act;
			}
		}
		else {
			$feedback = qq!<p><span style="color: red">No modem selected.</span>!;
			undef $act;
		}
	}

	#view a message thread
	elsif ( defined $act and $act eq "view_thread" ) {

		if (defined $modem) {
			my ($imei,$description,$enabled) = (undef, undef, 0);

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my $prep_stmt6 = $con->prepare("SELECT imei,description,enabled FROM modems WHERE id=? LIMIT 1");
			
			if ($prep_stmt6) {
				my $rc = $prep_stmt6->execute($modem);

				if ($rc) {
					while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
						$imei = $rslts[0];
						$description = $rslts[1];
						$enabled = $rslts[2]; 
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
			}
			if (defined $imei and $enabled) {
				#has a message id been specified?
				if ( defined $message_id ) {
	
					my $message_thread = "";

					#read thread
					#read sender
					my $sender = undef;
					my $prep_stmt8 = $con->prepare("SELECT sender FROM inbox WHERE modem=? AND message_id=?");
			
					if ($prep_stmt8) {
	
						my $rc = $prep_stmt8->execute($modem, $message_id);
					
						if ($rc) {
							while ( my @rslts = $prep_stmt8->fetchrow_array() ) {
								$sender = $rslts[0];
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM inbox: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM inbox: ", $con->errstr,$/;
					}
				
					$message_thread = "<em>No such message.</em>";
					if (defined $sender) {
						$message_thread = "";
						my %msgs;	
						#a join might work but not very gracefully.

						my $prep_stmt9 = $con->prepare("SELECT message_id,text,time FROM inbox WHERE modem=? AND sender=?");
			
						if ($prep_stmt9) {
	
							my $rc = $prep_stmt9->execute($modem, $sender);
						
							if ($rc) {
								while ( my @rslts = $prep_stmt9->fetchrow_array() ) {
									$msgs{$rslts[0]} = {"text" => $rslts[1], "time" => $rslts[2]};
								}
							}
							else {
								print STDERR "Could not execute SELECT FROM inbox: ", $con->errstr, $/;
							}

						}
						else {
							print STDERR "Could not prepare SELECT FROM inbox: ", $con->errstr,$/;
						}

						my $prep_stmt10 = $con->prepare("SELECT message_id,text,time FROM sent_messages WHERE modem=? AND (LOCATE(TRIM(LEADING '0' FROM recipient), ?) > 0)");
			
						if ($prep_stmt10) {
	
							my $rc = $prep_stmt10->execute($modem, $sender);
						
							if ($rc) {
								while ( my @rslts = $prep_stmt10->fetchrow_array() ) {
									$msgs{$rslts[0]} = {"text" => $rslts[1], "time" => $rslts[2], "own" => 1};
								}
							}
							else {
								print STDERR "Could not execute SELECT FROM sent_messages: ", $con->errstr, $/;
							}

						}
						else {
							print STDERR "Could not prepare SELECT FROM sent_messages: ", $con->errstr,$/;
						}

						#lookup senders
						my %all_contacts;
						my $prep_stmt11 = $con->prepare("SELECT id,name,phone_no FROM contacts");
		
						if ($prep_stmt11) {

							my $rc = $prep_stmt11->execute();

							if ($rc) {

								while ( my @rslts = $prep_stmt11->fetchrow_array() ) {
									my @numbers = split/,/,$rslts[2];

									for my $number (@numbers) {
										#users are likely to use shorthand for numbers 
										$number =~ s/^0*//;

										my $descr = "$rslts[0]($rslts[1])";
										$all_contacts{$number} = $descr;
									}	
								}

								#lookup longest numbers to avoid short numbers
								#that fit anything.
								for my $num ( sort { length($b) <=> length($a) } keys %all_contacts ) {

									#resembles something in the contacts
									if (index($sender, $num) >= 0 or index($num, $sender) >= 0) {
										$sender = $all_contacts{$num};
										last;
									}
								}

							}
							else {
								print STDERR "Could not execute SELECT FROM contacts: ", $con->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare SELECT FROM contacts: ", $con->errstr,$/;
						}
						
						for my $msg (sort {$msgs{$b}->{"time"} cmp $msgs{$a}->{"time"}} keys %msgs) {

							my $from = $sender;
							if (exists $msgs{$msg}->{"own"}) {
								$from = "Me";
							}
							my $p_style = "";
					
							#give the message the user clicked on a blue
							#background
							if ($msg == $message_id) {
								$p_style = qq! style="background-color: #A9E2F3"!;
							}

							$message_thread .= 
qq!
<p$p_style><A name="$msg"><SPAN style="font-weight: bold">$from</SPAN>: $msgs{$msg}->{"text"}</A><br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<SPAN style="font-weight: bold">$msgs{$msg}->{"time"}</SPAN>
<HR>
!
						}

						#update message_read for all these messages
						my @where_clause_bts;
						foreach (keys %msgs) {
							push @where_clause_bts, "message_id=?";
						}
	
						my $where_clause = join(" OR ", @where_clause_bts);

						my $prep_stmt6 = $con->prepare("UPDATE inbox SET message_read=2 WHERE modem=? AND ($where_clause)");

						if ($prep_stmt6) {
							my $rc = $prep_stmt6->execute($modem, keys %msgs);
							if ($rc) {
								$con->commit();
							}
							else {
								print STDERR "Could not execute UPDATE inbox: ", $con->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare UPDATE inbox: ", $con->errstr, $/;
						}

					}

					#how many messages are there?
					my $unread_msgs = 0;

					my $prep_stmt7 = $con->prepare("SELECT COUNT(message_id) FROM inbox WHERE modem=? AND message_read != 2");
			
					if ($prep_stmt7) {

						my $rc = $prep_stmt7->execute($modem);
						if ($rc) {
							while ( my @rslts = $prep_stmt7->fetchrow_array() ) {
								$unread_msgs = $rslts[0];
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM inbox: ", $con->errstr, $/;
						}

					}
					else {
						print STDERR "Could not prepare SELECT FROM inbox: ", $con->errstr,$/;
					}
				
					my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/message.cgi">Send Messages</a> --&gt; <a href="/cgi-bin/message.cgi?act=view_modem&modem=$modem">View Modem</a>
	<hr>
};

					$content =
qq*
<!DOCTYPE html>

<html lang="en">

<head>

<script type="text/javascript">

var num_unread_msgs = $unread_msgs;

var httpRequest;
var waiting = 0;
var cntr = 0;
var num_re = /^[0-9]+\$/;

var url = '';

function toggle_all() {

	var new_state = document.getElementById("check_all").checked;
	for (var i = 0; i < message_ids.length; i++) {
		document.getElementById("message_id_" + message_ids[i]).checked = new_state;	
	}
}

function init() {

	if (window.XMLHttpRequest) { 
		httpRequest = new XMLHttpRequest();
	}
	else if (window.ActiveXObject) {
		try {
			httpRequest = new ActiveXObject("Msxml2.XMLHTTP");
		}
		catch (e) {
			try {
				httpRequest = new ActiveXObject("Microsoft.XMLHTTP");
			}
			catch (e) {}
		}
	}

	window.setInterval(reload, 5000);

	url = window.location.protocol + '//' + window.location.hostname;	
}

function reload() {
	
	if (httpRequest) {

		if (waiting) {
			return;	
		}

		waiting = 1;

		httpRequest.open('GET', url + '/cgi-bin/message.cgi?modem=$modem&act=refresh_inbox&cntr=' + (++cntr) , false);
		httpRequest.setRequestHeader('Content-Type', 'text/plain');
		httpRequest.setRequestHeader('Cache-Control', 'no-cache');
		httpRequest.send();
		
		if (httpRequest.status === 200) {

			var result_txt = httpRequest.responseText;
	
			if ( result_txt.match(num_re) ) {

				var num_new_msgs = parseInt(result_txt);
				num_unread_msgs += num_new_msgs;
				
				document.getElementById("num_unread_container").innerHTML = "(" + num_unread_msgs + ")";	

			}
		}

		waiting = 0;
	}
}

</script>

<title>Messenger - Send Messages - View Thread</title>

</head>

<body onload="init()">
$header
$feedback

<TABLE cellspacing="15%">
<TR>

<TD style="width: 15%; border-right: solid;vertical-align: top">

<h3><a href="/cgi-bin/message.cgi?act=view_inbox&modem=$modem">Inbox<span id="num_unread_container">($unread_msgs)</span></a></h3>
<h3><a href="/cgi-bin/message.cgi?act=view_sent&modem=$modem">Sent Messages</a></h3>

<TD style="width: 80%">
$message_thread
</TABLE>

</body>
</html>
*;
				}
				else {
					$feedback = qq!<p><span style="color: red">No message selected.</span>!;
					$act = "view_inbox";
				}
			}
			#no such modem
			else {
				$feedback = qq!<p><span style="color: red">The modem specified does not exist.</span>!;
				undef $act;
			}
		}
		else {
			$feedback = qq!<p><span style="color: red">No modem selected.</span>!;
			undef $act;
		}
	}
	#view inbox
	if ( defined $act and $act eq "view_inbox" ) {

		if (defined $modem) {
			my ($imei,$description,$enabled) = (undef, undef, 0);

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my $prep_stmt6 = $con->prepare("SELECT imei,description,enabled FROM modems WHERE id=? LIMIT 1");
			
			if ($prep_stmt6) {
				my $rc = $prep_stmt6->execute($modem);

				if ($rc) {
					while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
						$imei = $rslts[0];
						$description = $rslts[1];
						$enabled = $rslts[2]; 
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
			}
			if (defined $imei and $enabled) {
			
				#has this request been init'd?
				my $num_msgs = 0;
				my $unread_msgs = 0;

				my $qry_url_bt = "";
				my $qry = "";
				my $search_field_value = "";

				if ($query_mode) {
					$qry = " AND (text LIKE ? OR sender LIKE ?) ";
					$qry_url_bt = "q=$encd_search_str&";
					$search_field_value = htmlspecialchars($search_string);
				}
	
				my $prep_stmt7 = $con->prepare("SELECT message_read,COUNT(message_id) FROM inbox WHERE modem=?${qry}GROUP BY message_read");
			
				if ($prep_stmt7) {
					my $rc;
					#pass search string
					if ( $query_mode ) {
						$rc = $prep_stmt7->execute($modem, "%${search_string}%", "%${search_string}%");
					}
					else {
						$rc = $prep_stmt7->execute($modem);
					}

					if ($rc) {
						while ( my @rslts = $prep_stmt7->fetchrow_array() ) {

							$num_msgs += $rslts[1];
							#0 and 1 represent unread msgs
							if ($rslts[0] == 0 or $rslts[0] == 1) {
								$unread_msgs += $rslts[1];
							}
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM inbox: ", $con->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM inbox: ", $con->errstr,$/;
				}

				
				my $per_page_guide = "";

				if ($num_msgs > 10) {
					$per_page_guide .= "<p><em>Messages per page</em>: <span style='word-spacing: 1em'>";
					for my $row_cnt (10, 20, 50, 100) {
						if ($row_cnt == $per_page) {
							$per_page_guide .= " <span style='font-weight: bold'>$row_cnt</span>";
						}
						else {
							my $re_ordered_page = $page;
							if ($page > 1) {
								my $preceding_results = $per_page * ($page - 1);
								$re_ordered_page = $preceding_results / $row_cnt;
								#if results will overflow into the next
								#page, bump up the page number
								#save that as an integer
								$re_ordered_page++ unless ($re_ordered_page < int($re_ordered_page));
								$re_ordered_page = int($re_ordered_page);
							}
							$per_page_guide .= " <a href='/cgi-bin/message.cgi?act=view_inbox&modem=$modem&${qry_url_bt}pg=$re_ordered_page&per_page=$row_cnt'>$row_cnt</a>";
						}
					}
					$per_page_guide .= "</span>";
				}
		
				my $limit_clause = "";
	
				my $page_guide = "";	
				my $res_pages = $num_msgs / $per_page;
				if ($res_pages > 1) {

					if (int($res_pages) < $res_pages) {
						$res_pages = int($res_pages) + 1;
					}

					my $start = $per_page * ($page - 1);	
					$limit_clause = " LIMIT $start, $per_page";
				}

				if ($res_pages > 1) {
					$page_guide .= '<table cellspacing="50%"><tr>';

					if ($page > 1) {
						$page_guide .= "<td><a href='/cgi-bin/message.cgi?act=view_inbox&modem=$modem&${qry_url_bt}pg=".($page - 1) ."'>Prev</a>";
					}

					if ($page < 10) {
						for (my $i = 1; $i <= $res_pages and $i < 11; $i++) {
							if ($i == $page) {
								$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
							}
							else {
								$page_guide .= "<td><a href='/cgi-bin/message.cgi?act=view_inbox&modem=$modem&${qry_url_bt}pg=$i'>$i</a>";
							}
						}
					}
					else {
						for (my $i = $page - 4; $i <= $res_pages and $i < ($page + 4); $i++) {
							if ($i == $page) {
								$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
							}
							else {
								$page_guide .= "<td><a href='/cgi-bin/message.cgi?act=view_inbox&modem=$modem&${qry_url_bt}pg=$i'>$i</a>";
							}
						}
					}
					if ($page < $res_pages) {
						$page_guide .= "<td><a href='/cgi-bin/message.cgi?act=view_inbox&modem=$modem&${qry_url_bt}pg=". ($page + 1) . "'>Next</a>";
					}
					$page_guide .= '</table>';
				}

				my $search_results = "There're no messages in the inbox.";
				if ($query_mode) {
					my $search_results = "Your search did not match any messages in the inbox.";
				}

				my @msg_ids = ();

				if ($num_msgs > 0) {

					my $conf_code = gen_token();
					$session{"confirm_code"} = $conf_code;

					$search_results = 
qq!
<FORM method="POST" action="/cgi-bin/message.cgi?act=view_inbox&modem=$modem&${qry_url_bt}pg=$page">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<TABLE border="1">
<THEAD>
<TH><INPUT type="checkbox" onclick="toggle_all()" id="check_all"><TH>Sender<TH>Text<TH>Time
</THEAD>
<TBODY>
!;

					my %senders_lookup = ();
					
					my $prep_stmt8 = $con->prepare("SELECT message_id,sender,text,time,message_read FROM inbox WHERE modem=?${qry}ORDER BY time DESC${limit_clause}");
			
					if ($prep_stmt8) {
						my $rc;
						#pass search string
						if ( $query_mode ) {
							$rc = $prep_stmt8->execute($modem, "%${search_string}%", "%${search_string}%");
						}
						else {
							$rc = $prep_stmt8->execute($modem);
						}

						if ($rc) {
							while ( my @rslts = $prep_stmt8->fetchrow_array() ) {

								push @msg_ids, $rslts[0];

								
								my $sender = htmlspecialchars($rslts[1]);

								my $text_length = length($rslts[2]);
								#only show 50 char snippets
								if ($text_length > 50) {
									$rslts[2] = substr($rslts[2], 0, 50) . "...";
								}

								my $text = htmlspecialchars($rslts[2]);

								#bold the first 20 characters of unread messages
								my $row_style = "";
								if ($rslts[4] != 2) {	
									$row_style = qq! style="font-weight: bold"!;
								}

								$search_results .= qq!<TR${row_style}><TD><INPUT id="message_id_$rslts[0]" type="checkbox" name="message_id_$rslts[0]" value="$rslts[0]"><TD id="_sender_$sender">$sender<TD><a href="/cgi-bin/message.cgi?act=view_thread&modem=$modem&message_id=$rslts[0]#$rslts[0]">$text</a><TD>$rslts[3]!;
	
								$senders_lookup{$sender} = undef;
								#load all contacts;
								my %all_contacts;
								
							}

							#lookup senders
							my %all_contacts;
							my $prep_stmt10 = $con->prepare("SELECT id,name,phone_no FROM contacts");
			
							if ($prep_stmt10) {

								my $rc = $prep_stmt10->execute();

								if ($rc) {

									while ( my @rslts = $prep_stmt10->fetchrow_array() ) {
										my @numbers = split/,/,$rslts[2];

										for my $number (@numbers) {
											#users are likely to use shorthand for numbers 
											$number =~ s/^0*//;

											my $descr = "$rslts[0]($rslts[1])";
											$all_contacts{$number} = $descr;
										}
									}

									#lookup longest numbers to avoid short numbers
									#that fit anything.
									for my $num ( sort { length($b) <=> length($a) } keys %all_contacts ) {

										for my $lookup ( keys %senders_lookup ) {
											#resembles something in the 
											if (index($lookup, $num) >= 0 or index($num, $lookup) >= 0) {
												$senders_lookup{$lookup} = $all_contacts{$num};
												last;
											}
										}

									}

									#replace matched raw numbers in search results
									for my $sender_num (keys %senders_lookup) {

										my $name = $senders_lookup{$sender_num};
										next if (not defined $name);

										my $len = length(qq!<TD id="_sender_$sender_num">$sender_num!);
										my $index = index($search_results, qq!<TD id="_sender_$sender_num">$sender_num!);
	
										substr($search_results, $index, $len, "<TD>$name");
	
									}
								}
								else {
									print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
								}
							}
							else {
								print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
					}

					$search_results .= qq!
</TBODY>
</TABLE>
<p><INPUT type="submit" name="read" value="Mark as Read">&nbsp;&nbsp;<INPUT type="submit" name="unread" value="Mark as Unread">
</FORM>
!
				}

				my $msg_ids = "[" . join(", ", @msg_ids) . "]";

				my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/message.cgi">Send Messages</a> --&gt; <a href="/cgi-bin/message.cgi?act=view_modem&modem=$modem">View Modem</a>
	<hr> 
};
				$content =
qq*
<!DOCTYPE html>

<html lang="en">

<head>

<script type="text/javascript">

var message_ids = $msg_ids;
var num_unread_msgs = $unread_msgs;

var httpRequest;
var waiting = 0;
var cntr = 0;
var num_re = /^[0-9]+\$/;

var url = '';

function toggle_all() {

	var new_state = document.getElementById("check_all").checked;
	for (var i = 0; i < message_ids.length; i++) {
		document.getElementById("message_id_" + message_ids[i]).checked = new_state;	
	}
}

function init() {

	if (window.XMLHttpRequest) { 
		httpRequest = new XMLHttpRequest();
	}
	else if (window.ActiveXObject) {
		try {
			httpRequest = new ActiveXObject("Msxml2.XMLHTTP");
		}
		catch (e) {
			try {
				httpRequest = new ActiveXObject("Microsoft.XMLHTTP");
			}
			catch (e) {}
		}
	}

	window.setInterval(reload, 5000);

	url = window.location.protocol + '//' + window.location.hostname;	
}

function reload() {
	
	if (httpRequest) {

		if (waiting) {
			return;	
		}

		waiting = 1;

		httpRequest.open('GET', url + '/cgi-bin/message.cgi?modem=$modem&act=refresh_inbox&cntr=' + (++cntr) , false);
		httpRequest.setRequestHeader('Content-Type', 'text/plain');
		httpRequest.setRequestHeader('Cache-Control', 'no-cache');
		httpRequest.send();
		
		if (httpRequest.status === 200) {

			var result_txt = httpRequest.responseText;
	
			if ( result_txt.match(num_re) ) {

				var num_new_msgs = parseInt(result_txt);
				num_unread_msgs += num_new_msgs;
				
				document.getElementById("num_unread_container").innerHTML = "(" + num_unread_msgs + ")";	

			}
		}

		waiting = 0;
	}
}
</script>

<title>Messenger - Send Messages - Inbox</title>

</head>

<body onload="init()">
$header
$feedback
<TABLE>
<TR>
<TD style="width: 50%">
$per_page_guide
<TD>
<FORM method="GET" action="/cgi-bin/message.cgi">
<INPUT type="hidden" name="act" value="view_inbox">
<INPUT type="hidden" name="modem" value="$modem"> 
<INPUT type="text" name="q" value="$search_field_value" size="30">&nbsp;&nbsp;<INPUT type="submit" name="search" value="Search">
</FORM>
</TABLE>
<HR>

<TABLE cellspacing="15%">
<TR>
<TD style="width: 15%; border-right: solid;vertical-align: top">

<h3><a href="/cgi-bin/message.cgi?act=view_inbox&modem=$modem">Inbox<span id="num_unread_container">($unread_msgs)</span></a></h3>
<h3><a href="/cgi-bin/message.cgi?act=view_sent&modem=$modem">Sent Messages</a></h3>
<TD style="width: 80%">
$search_results
</TABLE>
$page_guide
</body>
</html>
*;

			}
			#no such modem
			else {
				$feedback = qq!<p><span style="color: red">The modem specified does not exist.</span>!;
				undef $act;
			}
		}
		else {
			$feedback = qq!<p><span style="color: red">No modem selected.</span>!;
			undef $act;
		}
	}

	#view sent mail
	if ( defined $act and $act eq "view_sent" ) {

		if (defined $modem) {
			my ($imei,$description,$enabled) = (undef, undef, 0);

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my $prep_stmt6 = $con->prepare("SELECT imei,description,enabled FROM modems WHERE id=? LIMIT 1");
			
			if ($prep_stmt6) {
				my $rc = $prep_stmt6->execute($modem);

				if ($rc) {
					while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
						$imei = $rslts[0];
						$description = $rslts[1];
						$enabled = $rslts[2]; 
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
			}
			if (defined $imei and $enabled) {
			
				#has this request been init'd?
				my $num_msgs = 0;
				my $unread_msgs = 0;

				my $qry_url_bt = "";
				my $qry = "";
				my $search_field_value = "";

				if ($query_mode) {
					$qry = " AND (text LIKE ? OR recipient LIKE ?) ";
					$qry_url_bt = "q=$encd_search_str&";
					$search_field_value = htmlspecialchars($search_string);
				}
	
				my $prep_stmt7 = $con->prepare("SELECT COUNT(message_id) FROM sent_messages WHERE modem=?${qry}");
			
				if ($prep_stmt7) {
					my $rc;
					#pass search string
					if ( $query_mode ) {
						$rc = $prep_stmt7->execute($modem, "%${search_string}%", "%${search_string}%");
					}
					else {
						$rc = $prep_stmt7->execute($modem);
					}

					if ($rc) {
						while ( my @rslts = $prep_stmt7->fetchrow_array() ) {
							$num_msgs = $rslts[0];
						}

					}
					else {
						print STDERR "Could not execute SELECT FROM sent_messages: ", $con->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM sent_messages: ", $con->errstr,$/;
				}

				
				my $per_page_guide = "";

				if ($num_msgs > 10) {
					$per_page_guide .= "<p><em>Messages per page</em>: <span style='word-spacing: 1em'>";
					for my $row_cnt (10, 20, 50, 100) {
						if ($row_cnt == $per_page) {
							$per_page_guide .= " <span style='font-weight: bold'>$row_cnt</span>";
						}
						else {
							my $re_ordered_page = $page;
							if ($page > 1) {
								my $preceding_results = $per_page * ($page - 1);
								$re_ordered_page = $preceding_results / $row_cnt;
								#if results will overflow into the next
								#page, bump up the page number
								#save that as an integer
								$re_ordered_page++ unless ($re_ordered_page < int($re_ordered_page));
								$re_ordered_page = int($re_ordered_page);
							}
							$per_page_guide .= " <a href='/cgi-bin/message.cgi?act=view_sent&modem=$modem&${qry_url_bt}pg=$re_ordered_page&per_page=$row_cnt'>$row_cnt</a>";
						}
					}
					$per_page_guide .= "</span>";
				}
		
				my $limit_clause = "";
	
				my $page_guide = "";	
				my $res_pages = $num_msgs / $per_page;
				if ($res_pages > 1) {

					if (int($res_pages) < $res_pages) {
						$res_pages = int($res_pages) + 1;
					}

					my $start = $per_page * ($page - 1);	
					$limit_clause = " LIMIT $start, $per_page";
				}

				if ($res_pages > 1) {
					$page_guide .= '<table cellspacing="50%"><tr>';

					if ($page > 1) {
						$page_guide .= "<td><a href='/cgi-bin/message.cgi?act=view_sent&modem=$modem&${qry_url_bt}pg=".($page - 1) ."'>Prev</a>";
					}

					if ($page < 10) {
						for (my $i = 1; $i <= $res_pages and $i < 11; $i++) {
							if ($i == $page) {
								$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
							}
							else {
								$page_guide .= "<td><a href='/cgi-bin/message.cgi?act=view_sent&modem=$modem&${qry_url_bt}pg=$i'>$i</a>";
							}
						}
					}
					else {
						for (my $i = $page - 4; $i <= $res_pages and $i < ($page + 4); $i++) {
							if ($i == $page) {
								$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
							}
							else {
								$page_guide .= "<td><a href='/cgi-bin/message.cgi?act=view_sent&modem=$modem&${qry_url_bt}pg=$i'>$i</a>";
							}
						}
					}
					if ($page < $res_pages) {
						$page_guide .= "<td><a href='/cgi-bin/message.cgi?act=view_sent&modem=$modem&${qry_url_bt}pg=". ($page + 1) . "'>Next</a>";
					}
					$page_guide .= '</table>';
				}

				my $search_results = "There're no messages in the outbox.";
				if ($query_mode) {
					my $search_results = "Your search did not match any messages in the outbox.";
				}

				my @msg_ids = ();

				if ($num_msgs > 0) {

					my $conf_code = gen_token();
					$session{"confirm_code"} = $conf_code;

					$search_results = 
qq!
<TABLE border="1">
<THEAD>
<TH>Recipient<TH>Text<TH>Time
</THEAD>
<TBODY>
!;
		
					my $prep_stmt8 = $con->prepare("SELECT recipient,text,time FROM sent_messages WHERE modem=?${qry}ORDER BY time DESC${limit_clause}");
			
					if ($prep_stmt8) {
						my $rc;
						#pass search string
						if ( $query_mode ) {
							$rc = $prep_stmt8->execute($modem, "%${search_string}%", "%${search_string}%");
						}
						else {
							$rc = $prep_stmt8->execute($modem);
						}

						if ($rc) {
					
							my %recipients_lookup;

							while ( my @rslts = $prep_stmt8->fetchrow_array() ) {

								push @msg_ids, $rslts[0];

								my $trimmed_num = $rslts[0];
								$trimmed_num =~ s/^0*//;

								$recipients_lookup{$trimmed_num} = undef;

								my $recipient = htmlspecialchars($rslts[0]);

								my $text = htmlspecialchars($rslts[1]);

								$search_results .= qq!<TR><TD id="_recipient_$recipient">$recipient<TD>$text<TD>$rslts[2]!;
							}

							#lookup recipients
							my %all_contacts;
							my $prep_stmt10 = $con->prepare("SELECT id,name,phone_no FROM contacts");
			
							if ($prep_stmt10) {

								my $rc = $prep_stmt10->execute();

								if ($rc) {

									while ( my @rslts = $prep_stmt10->fetchrow_array() ) {

										my @numbers = split/,/,$rslts[2];

										for my $number (@numbers) {
											#users are likely to use shorthand for numbers 
											$number =~ s/^0*//;

											my $descr = "$rslts[0]($rslts[1])";
											$all_contacts{$number} = $descr;
										}

									}

									#lookup longest numbers to avoid short numbers
									#that fit anything.
									for my $num ( sort { length($b) <=> length($a) } keys %all_contacts ) {

										for my $lookup ( keys %recipients_lookup ) {
											#resembles something in the 
											if (index($lookup, $num) >= 0 or index($num, $lookup) >= 0) {
												$recipients_lookup{$lookup} = $all_contacts{$num};
												last;
											}
										}

									}

									#replace matched raw numbers in search results
									for my $recipient_num (keys %recipients_lookup) {

										my $name = $recipients_lookup{$recipient_num};
										next if (not defined $name);

										my $len = length(qq!<TD id="_recipient_$recipient_num">$recipient_num!);
										my $index = index($search_results, qq!<TD id="_recipient_$recipient_num">$recipient_num!);
	
										substr($search_results, $index, $len, "<TD>$name");
	
									}
								}
								else {
									print STDERR "Could not execute SELECT FROM contacts: ", $con->errstr, $/;
								}
							}
							else {
								print STDERR "Could not prepare SELECT FROM contacts: ", $con->errstr,$/;
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM inbox: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM inbox: ", $con->errstr,$/;
					}


					$search_results .= qq!
</TBODY>
</TABLE>
!;
				}

				my $msg_ids = "[" . join(", ", @msg_ids) . "]";

				my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/message.cgi">Send Messages</a> --&gt; <a href="/cgi-bin/message.cgi?act=view_modem&modem=$modem">View Modem</a>
	<hr> 
};
				$content =
qq*
<!DOCTYPE html>

<html lang="en">

<head>

<script type="text/javascript">

var message_ids = $msg_ids;
var num_unread_msgs = $unread_msgs;

var httpRequest;
var waiting = 0;
var cntr = 0;
var num_re = /^[0-9]+\$/;

var url = '';

function toggle_all() {

	var new_state = document.getElementById("check_all").checked;
	for (var i = 0; i < message_ids.length; i++) {
		document.getElementById("message_id_" + message_ids[i]).checked = new_state;	
	}
}

function init() {

	if (window.XMLHttpRequest) { 
		httpRequest = new XMLHttpRequest();
	}
	else if (window.ActiveXObject) {
		try {
			httpRequest = new ActiveXObject("Msxml2.XMLHTTP");
		}
		catch (e) {
			try {
				httpRequest = new ActiveXObject("Microsoft.XMLHTTP");
			}
			catch (e) {}
		}
	}

	window.setInterval(reload, 5000);

	url = window.location.protocol + '//' + window.location.hostname;	
}

function reload() {
	
	if (httpRequest) {

		if (waiting) {
			return;	
		}

		waiting = 1;

		httpRequest.open('GET', url + '/cgi-bin/message.cgi?modem=$modem&act=refresh_inbox&cntr=' + (++cntr) , false);
		httpRequest.setRequestHeader('Content-Type', 'text/plain');
		httpRequest.setRequestHeader('Cache-Control', 'no-cache');
		httpRequest.send();
		
		if (httpRequest.status === 200) {

			var result_txt = httpRequest.responseText;
	
			if ( result_txt.match(num_re) ) {

				var num_new_msgs = parseInt(result_txt);
				num_unread_msgs += num_new_msgs;
				
				document.getElementById("num_unread_container").innerHTML = "(" + num_unread_msgs + ")";	

			}
		}

		waiting = 0;
	}
}
</script>

<title>Messenger - Send Messages - Inbox</title>

</head>

<body onload="init()">
$header
$feedback
<TABLE>
<TR>
<TD style="width: 50%">
$per_page_guide
<TD>
<FORM method="GET" action="/cgi-bin/message.cgi">
<INPUT type="hidden" name="act" value="view_inbox">
<INPUT type="hidden" name="modem" value="$modem"> 
<INPUT type="text" name="q" value="$search_field_value" size="30">&nbsp;&nbsp;<INPUT type="submit" name="search" value="Search">
</FORM>
</TABLE>
<HR>

<TABLE cellspacing="15%">
<TR>
<TD style="width: 15%; border-right: solid;vertical-align: top">

<h3><a href="/cgi-bin/message.cgi?act=view_inbox&modem=$modem">Inbox<span id="num_unread_container">($unread_msgs)</span></a></h3>
<h3><a href="/cgi-bin/message.cgi?act=view_sent&modem=$modem">Sent Messages</a></h3>
<TD style="width: 80%">
$search_results
</TABLE>
$page_guide
</body>
</html>
*;

			}
			#no such modem
			else {
				$feedback = qq!<p><span style="color: red">The modem specified does not exist.</span>!;
				undef $act;
			}
		}
		else {
			$feedback = qq!<p><span style="color: red">No modem selected.</span>!;
			undef $act;
		}
	}
	#make ussd request
	elsif (defined $act and $act eq "ussd_request") {

		if (defined $modem) {
			#look up modem in modems DB,
			#look it up with ModemManager
			#save path to session for 
			#faster access
			if ($ussd_stage == 1) {

				my ($imei,$description,$enabled) = (undef, undef, 0);

				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				my $prep_stmt6 = $con->prepare("SELECT imei,description,enabled FROM modems WHERE id=? LIMIT 1");
			
				if ($prep_stmt6) {
					my $rc = $prep_stmt6->execute($modem);

					if ($rc) {
						while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
							$imei = $rslts[0];
							$description = $rslts[1];
							$enabled = $rslts[2]; 
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
				}
		
				#found this modem
				if (defined $imei and $enabled) {

					my $path = undef;
					#get modem path
					if ($modem_manager1) {

						eval {
							my $bus = Net::DBus->system;
							my $modem_manager = $bus->get_service("org.freedesktop.ModemManager1");

							my $mm_obj = $modem_manager->get_object("/org/freedesktop/ModemManager1");
							my $mm_obj_manager = $mm_obj->as_interface("org.freedesktop.DBus.ObjectManager");

							my $modem_list = $mm_obj_manager->GetManagedObjects();

							if (ref($modem_list) eq "HASH") {

								for my $modem_path ( keys %{$modem_list} ) {

									my $modem_obj = $modem_manager->get_object($modem_path);
									my $props_iface = $modem_obj->as_interface("org.freedesktop.DBus.Properties");
									my $modem_iface = $modem_obj->as_interface("org.freedesktop.ModemManager1.Modem");

									my $modem_description = uc($props_iface->Get("org.freedesktop.ModemManager1.Modem", "Manufacturer") . " " . $props_iface->Get("org.freedesktop.ModemManager1.Modem", "Model"));
									my $modem_imei = $props_iface->Get("org.freedesktop.ModemManager1.Modem", "EquipmentIdentifier");

									if ($modem_imei eq $imei and $modem_description eq $description) {
										$path = $modem_path;
										last;
									}
								}

							}

						};
					}
					#modemmanager0.6
					else {	
						#wrapped in an eval--DBus/ModemManager
						eval {
							my $bus = Net::DBus->system;	
							my $modem_manager = $bus->get_service("org.freedesktop.ModemManager");

							#$content = dbus_dump($modem_manager);

							my $get_list = $modem_manager->get_object("/org/freedesktop/ModemManager", "org.freedesktop.ModemManager");
							my $list_modems = $get_list->EnumerateDevices();
							 
							#there're some modems attached
							if (ref($list_modems) eq "ARRAY") {
		
								for my $modem_name (@{$list_modems}) {
									
									my $modem_obj = $modem_manager->get_object($modem_name);
									my $props_iface = $modem_obj->as_interface("org.freedesktop.DBus.Properties");	

									my $modem_iface = $modem_obj->as_interface("org.freedesktop.ModemManager.Modem");

									my @description_bts = @{$modem_iface->GetInfo()};
									my $modem_description = uc("$description_bts[0] $description_bts[1]");
									my $modem_imei = $props_iface->Get("org.freedesktop.ModemManager.Modem", "EquipmentIdentifier");

									#same modem
									#i check both the description and 
									#the imei because there're a lot of
									#fishy phones that pick IMEIs at random
									#but not too many that pick both IMEIs
									#and make/models at random.
									if ($modem_imei eq $imei and $modem_description eq $description) {	
										$path = $modem_name;
										last;
									}
								}
							}

						};

						if ($@) {
							print STDERR "Could not find modem $modem: $@\n";
						}

						#update modem DB
						elsif (defined $path) {
							$session{"modem_path"} = $path;

							my $conf_code = gen_token();
							$session{"confirm_code"} = $conf_code;

							$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<SCRIPT type="text/javascript">

var mmi_code_re = new RegExp('^[\*\#]?[\*\#]?[0-9]?([\*0-9])\*\#?\$');

function check_mmi_code() {
	var input_mmi_code = document.getElementById("mmi_code").value;
	if (input_mmi_code.length > 0) {
		if (input_mmi_code.match(mmi_code_re)) {
			document.getElementById("dial").disabled = 0;
			document.getElementById("mmi_error_asterisk").innerHTML = "";
			document.getElementById("mmi_error").innerHTML = "";
		}
		else {
			document.getElementById("dial").disabled = 1;
			document.getElementById("mmi_error_asterisk").innerHTML = "\*";
			document.getElementById("mmi_error").innerHTML = "Invalid MMI code";
		}
	}
	else {
		document.getElementById("dial").disabled = 1; 
		document.getElementById("mmi_error_asterisk").innerHTML = "";
		document.getElementById("mmi_error").innerHTML = "";
	}
}

function init() {
	document.getElementById("dial").disabled = 1;
}

</SCRIPT>
<title>Messenger - Send Messages - USSD Request</title>
</head>

<body onload="init()">

<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/message.cgi">Send Messages</a> --&gt; <a href="/cgi-bin/message.cgi?act=view_modem&modem=$modem">View Modem</a>

<hr>

<FORM method="POST" action="/cgi-bin/message.cgi?act=ussd_request&ussd_stage=2&modem=$modem">

<TABLE>
<TR><TD><span style="color: red" id="mmi_error_asterisk"></span><LABEL for="mmi_code">MMI Code<br>(e.g \*144#)</LABEL><TD><INPUT type="text" name="mmi_code" id="mmi_code" value="" onkeyup="check_mmi_code()" onmousemove="check_mmi_code()"><span style="color: red" id="mmi_error"></span>
<TR><TD colspan="2" style="text-align: centre"><INPUT type="submit" name="dial" id="dial" value="Dial">
</TABLE>

<INPUT type="hidden" name="confirm_code" value="$conf_code">

</FORM>

</body>
</html>
*;
						}
						else {
							$feedback = qq!<p><span style="color: red">The modem selected for the USSD request could not be found.</span> Perhaps it was disconnected.!;
							undef $act;
						}
					}
				}
				#no such modem
				else {
					$feedback = qq!<p><span style="color: red">The modem selected for the USSD request does not exist.</span>!;
					undef $act;
				}
			}
		}
		else {
			$feedback = qq!<p><span style="color: red">No modem selected for this USSD request.</span>!;
			undef $act;
		}
	}

	elsif (defined $act and $act eq "send_message") {
		if (defined $modem) {
			my ($imei,$description,$enabled) = (undef, undef, 0);

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my $prep_stmt6 = $con->prepare("SELECT imei,description,enabled FROM modems WHERE id=? LIMIT 1");
			
			if ($prep_stmt6) {
				my $rc = $prep_stmt6->execute($modem);

				if ($rc) {
					while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
						$imei = $rslts[0];
						$description = $rslts[1];
						$enabled = $rslts[2]; 
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
				}	
			}
			else {
				print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
			}
		
			#found this modem

			if (defined $imei and $enabled) {

				my $modem_path = undef;

				use Net::DBus qw(:typing);

				#wonder if I'll find this modemmanager version
				if ($modem_manager1) {

					eval {

						my $bus = Net::DBus->system;
						my $modem_manager = $bus->get_service("org.freedesktop.ModemManager1");

						my $mm_obj = $modem_manager->get_object("/org/freedesktop/ModemManager1");
						my $mm_obj_manager = $mm_obj->as_interface("org.freedesktop.DBus.ObjectManager");

						my $modem_list = $mm_obj_manager->GetManagedObjects();

						if ( ref($modem_list) eq "HASH" ) {

							for my $modem_name ( keys %{$modem_list} ) {

								my $modem_obj = $modem_manager->get_object($modem_name);
								my $props_iface = $modem_obj->as_interface("org.freedesktop.DBus.Properties");
								my $modem_iface = $modem_obj->as_interface("org.freedesktop.ModemManager1.Modem");

								my $modem_description = uc($props_iface->Get("org.freedesktop.ModemManager1.Modem", "Manufacturer") . " " . $props_iface->Get("org.freedesktop.ModemManager1.Modem", "Model"));
								my $modem_imei = $props_iface->Get("org.freedesktop.ModemManager1.Modem", "EquipmentIdentifier");

								if ($modem_imei eq $imei and $modem_description eq $description) {
									$modem_path = $modem_name;
									last;
								}
							}
						}
					};

				}
				#modemmanager0.6
				else {	
					#wrapped in an eval--DBus/ModemManager
					eval {
						my $bus = Net::DBus->system;	
						my $modem_manager = $bus->get_service("org.freedesktop.ModemManager");

						#$content = dbus_dump($modem_manager);

						my $get_list = $modem_manager->get_object("/org/freedesktop/ModemManager", "org.freedesktop.ModemManager");
						my $list_modems = $get_list->EnumerateDevices();
							 
						#there're some modems attached
						if (ref($list_modems) eq "ARRAY") {
	
							for my $modem_name (@{$list_modems}) {
						
								my $modem_obj = $modem_manager->get_object($modem_name);
								my $props_iface = $modem_obj->as_interface("org.freedesktop.DBus.Properties");	

								my $modem_iface = $modem_obj->as_interface("org.freedesktop.ModemManager.Modem");

								my @description_bts = @{$modem_iface->GetInfo()};
								my $modem_description = uc("$description_bts[0] $description_bts[1]");
								my $modem_imei = $props_iface->Get("org.freedesktop.ModemManager.Modem", "EquipmentIdentifier");

								#same modem
								#i check both the description and 
								#the imei because there're a lot of
								#fishy phones that pick IMEIs at random
								#but not too many that pick both IMEIs
								#and make/models at random.
								if ($modem_imei eq $imei and $modem_description eq $description) {	
									$modem_path = $modem_name;
									last;
								}
							}
						}
					};
				}

				if ($@) {
					print STDERR "Could not disconnect modem $modem: $@\n";

					$feedback = qq!<p><span style="color: red">The modem selected for sending messages does not exist.</span> Perhaps it was disconnected.!;
					undef $act;				
				}

				elsif (defined $modem_path) {
					$session{"modem_path"} = $modem_path;

					my $conf_code = gen_token();
					$session{"confirm_code"} = $conf_code;

					$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Messenger - Send Messages - Send Message</title>
</head>

<body>

<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/message.cgi">Send Messages</a> --&gt; <a href="/cgi-bin/message.cgi?act=view_modem&modem=$modem">View Modem</a>

<hr>

<FORM method="POST" action="/cgi-bin/message.cgi?act=send_message&modem=$modem">

<TABLE>

<TR><TD><LABEL for="recipient">Recipient</LABEL><TD><INPUT type="text" name="recipient" value="" size="16">
<TR><TD><LABEL for="message">Message</LABEL><TD><TEXTAREA name="message" cols="30" rows="6"></TEXTAREA>
<TR><TD><LABEL for="expiry" title="How long to wait before delivery fails">Expires in</LABEL><TD>

<SELECT name="expiry" title="How long to wait before delivery fails">

<OPTION value="60">1 hour</OPTION>
<OPTION value="180">3 hours</OPTION>
<OPTION value="360">6 hours</OPTION>
<OPTION selected value="720">12 hours</OPTION>
<OPTION value="1440">1 day</OPTION>
<OPTION value="2880">2 days</OPTION>

</SELECT>

<TR><TD colspan="2"><INPUT type="submit" name="send" value="Send">

</TABLE>

<INPUT type="hidden" name="confirm_code" value="$conf_code">

</FORM>

</body>
</html>
*;
				}

			}
			#no such modem
			else {
				$feedback = qq!<p><span style="color: red">The modem selected for sending messages does not exist.</span>!;
				undef $act;
			}
		}
		else {
			$feedback = qq!<p><span style="color: red">No modem selected for sending messages.</span>!;
			undef $act;
		}
	}
	
	elsif (defined $act and $act eq "disconnect_modem") {

		if (defined $modem and ($disconnect_stage == 1 or $disconnect_stage ==2) ) {

			my ($imei,$description,$enabled) = (undef, undef, 0);

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my $prep_stmt6 = $con->prepare("SELECT imei,description,enabled FROM modems WHERE id=? LIMIT 1");
			
			if ($prep_stmt6) {
				my $rc = $prep_stmt6->execute($modem);

				if ($rc) {
					while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
						$imei = $rslts[0];
						$description = $rslts[1];
						$enabled = $rslts[2]; 
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
				}	
			}
			else {
				print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
			}
		
			#found this modem

			if (defined $imei and $enabled) {

				my $fall_through = 0;

				if ( $disconnect_stage == 1 ) {

					my %affected_jobs = (); 
					#active jobs--
					#an instruction of 2 indicates a suspended job

					my $prep_stmt7 = $con->prepare("SELECT id,name,number_messages,number_delivered FROM messaging_jobs WHERE modem=? AND instructions != 2");

					if ($prep_stmt7) {
						my $rc = $prep_stmt7->execute($modem);
						if ($rc) {
							while ( my @rslts = $prep_stmt7->fetchrow_array() ) {
	
								my $undelivered = $rslts[2] - $rslts[3];
							
								if ($undelivered > 0) {
									$affected_jobs{$rslts[0]} = {"name" => htmlspecialchars($rslts[1]), "undelivered" => $undelivered}; 
								}
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM messaging_jobs: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM messaging_jobs: ", $con->errstr, $/;
					}
					#warn user about affected jobs
					if (keys %affected_jobs) {

						my $conf_code = gen_token();
						$session{"confirm_code"} = $conf_code;

						$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Messenger - Send Messages - Disconnect Modem</title>
</head>

<body>

<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/message.cgi">Send Messages</a> --&gt; <a href="/cgi-bin/message.cgi?act=view_modem&modem=$modem">View Modem</a>

<hr>

<FORM method="POST" action="/cgi-bin/message.cgi?act=disconnect_modem&disconnect_stage=2&modem=$modem">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<p><em>Clicking 'Disconnect' will suspend the following jobs:</em>
<ul>
*;
						for my $affected_job (keys %affected_jobs) {
							$content .= 
qq!
<li><a href="/cgi-bin/message.cgi?act=view_job&job=$affected_job">${$affected_jobs{$affected_job}}{"name"}</a> (${$affected_jobs{$affected_job}}{"undelivered"} undelivered messages)
<INPUT type="hidden" name="job_$affected_job" value="$affected_job">
!;
						}

						$content .= 
qq!
</ul>
<p><INPUT type="submit" name="disconnect" value="Disconnect">
</FORM>
</body>
</html>
!;
					}
					else {
						$disconnect_stage = 2;
						$fall_through++;
					}
				}
				
		
				#allow fall-through for modems with no active jobs
				if ( $disconnect_stage == 2 ) {

					my $failed_suspend = "";

					unless ($fall_through) {
						
						#check confirm code
						#update messaging_jobs DB
						#signal processes
						if ( exists $auth_params{"confirm_code"} and exists $session{"confirm_code"} and $auth_params{"confirm_code"} eq $session{"confirm_code"} ) {

							my %jobs_to_suspend;
							my @where_clause_bts;

							for my $param (keys %auth_params) {
								if ( $param =~ /^job_(\d+)$/ ) {
									my $job_id = $1;
									if ($auth_params{$param} eq $job_id) {
										$jobs_to_suspend{$job_id}++;
										push @where_clause_bts, "id=?";
									}
								}
							}
	
							if (@where_clause_bts) {

								my $num_jobs = scalar(@where_clause_bts);
								my $where_clause_str = join(" OR ", @where_clause_bts);


								#get pid of jobs to suspend before deleting them 
								my $prep_stmt8 = $con->prepare("SELECT id,name,pid FROM messaging_jobs WHERE $where_clause_str LIMIT $num_jobs");

								if ($prep_stmt8) {
									my $rc = $prep_stmt8->execute(keys %jobs_to_suspend);
									if ($rc) {
										while ( my @rslts = $prep_stmt8->fetchrow_array() ) {
											$jobs_to_suspend{$rslts[0]} = { "name" => $rslts[1], "pid" => $rslts[2] };
										}
									}
									else {
										print STDERR "Could not execute SELECT FROM messaging_jobs: ", $con->errstr, $/;
									}
								}
								else {
									print STDERR "Could not prepare SELECT FROM messaging_jobs: ", $con->errstr, $/;
								}

								#update messaging jobs--set instructions to 2 (suspend)
								my $prep_stmt9 = $con->prepare("UPDATE messaging_jobs SET instructions=2 WHERE id=? LIMIT 1");
							
								my %failed_jobs;

								if ($prep_stmt9) {

									for my $job (keys %jobs_to_suspend) {

										my $rc = $prep_stmt9->execute($job);
										unless ($rc) {
											$failed_jobs{$job} = {"name" => ${$jobs_to_suspend{$job}}{"name"}, "pid" => ${$jobs_to_suspend{$job}}{"pid"}};
											delete $jobs_to_suspend{$job};
											print STDERR "Could not execute UPDATE messaging_jobs: ", $con->errstr, $/;
										}
									}
									$con->commit();
								}

								else {
									print STDERR "Could not prepare UPDATE messaging_jobs: ", $con->errstr, $/;
								}

								#signal appropriate job	
								for my $to_kill (keys %jobs_to_suspend) {
									my $killed = kill 2, ${$jobs_to_suspend{$to_kill}}{"pid"};
									if (not $killed) {
										$failed_jobs{$to_kill} = {"name" => ${$jobs_to_suspend{$to_kill}}{"name"}, "pid" => ${$jobs_to_suspend{$to_kill}}{"pid"}};
										delete $jobs_to_suspend{$to_kill};
									}
								}
								
								#log job suspends
								my @today = localtime;	
								my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
							
								open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

	      	 						if ($log_f) {

       									@today = localtime;	
									my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
									flock ($log_f, LOCK_EX) or print STDERR "Could not log suspend messaging job for 1 due to flock error: $!$/";
									seek ($log_f, 0, SEEK_END);
									
									for my $job (keys %jobs_to_suspend) {
										my $name = ${$jobs_to_suspend{$job}}{"name"};
										print $log_f "1 SUSPEND MESSAGING JOB $name $time\n";
									}

									flock ($log_f, LOCK_UN);
       									close $log_f;
       								}
								else {
									print STDERR "Could not log suspend messaging job for 1: $!\n";
								}

								#jobs that could not be suspended.
								if (keys %failed_jobs) {
									$failed_suspend =
qq!
<p><span style="color: red">Could not suspend the following jobs:</span>
<UL>
!;
									for my $job ( keys %failed_jobs ) {

										my $job_name = htmlspecialchars(${$failed_jobs{$job}}{"name"});

										$failed_suspend .= 
qq!
<LI><a href="/cgi-bin/message.cgi?act=view_job&job=$job">$job_name</a>
!;
									}
									$failed_suspend .= "</UL>";
								}
							}
						}
						else {
							$act = "view_modem";
							$feedback = qq!<p><span style="color: red">Invalid 'disconnect' request received.</span>!;
						}
					}

					#disable modem
					use Net::DBus qw(:typing);

					my $success = 0;
					my $modem_seen = 0;

					#wonder if I'll find this modemmanager version
					if ($modem_manager1) {

						eval {

							my $bus = Net::DBus->system;
							my $modem_manager = $bus->get_service("org.freedesktop.ModemManager1");

							my $mm_obj = $modem_manager->get_object("/org/freedesktop/ModemManager1");
							my $mm_obj_manager = $mm_obj->as_interface("org.freedesktop.DBus.ObjectManager");

							my $modem_list = $mm_obj_manager->GetManagedObjects();

							if ( ref($modem_list) eq "HASH" ) {

								for my $modem_name ( keys %{$modem_list} ) {

									my $modem_obj = $modem_manager->get_object($modem_name);
									my $props_iface = $modem_obj->as_interface("org.freedesktop.DBus.Properties");
									my $modem_iface = $modem_obj->as_interface("org.freedesktop.ModemManager1.Modem");

									my $modem_description = uc($props_iface->Get("org.freedesktop.ModemManager1.Modem", "Manufacturer") . " " . $props_iface->Get("org.freedesktop.ModemManager1.Modem", "Model"));
									my $modem_imei = $props_iface->Get("org.freedesktop.ModemManager1.Modem", "EquipmentIdentifier");

									if ( $modem_imei eq $imei and $modem_description eq $description ) {

										$modem_seen++;
										$modem_iface->Enable(0);
										$success++;
										last;
									}
								}
							}

						};

					}
					#modemmanager0.6
					else {	
						#wrapped in an eval--DBus/ModemManager
						eval {
							my $bus = Net::DBus->system;	
							my $modem_manager = $bus->get_service("org.freedesktop.ModemManager");

							#$content = dbus_dump($modem_manager);

							my $get_list = $modem_manager->get_object("/org/freedesktop/ModemManager", "org.freedesktop.ModemManager");
							my $list_modems = $get_list->EnumerateDevices();
							 
							#there're some modems attached
							if (ref($list_modems) eq "ARRAY") {
		
								for my $modem_name (@{$list_modems}) {
									
									my $modem_obj = $modem_manager->get_object($modem_name);
									my $props_iface = $modem_obj->as_interface("org.freedesktop.DBus.Properties");	

									my $modem_iface = $modem_obj->as_interface("org.freedesktop.ModemManager.Modem");

									my @description_bts = @{$modem_iface->GetInfo()};
									my $modem_description = uc("$description_bts[0] $description_bts[1]");
									my $modem_imei = $props_iface->Get("org.freedesktop.ModemManager.Modem", "EquipmentIdentifier");

									#same modem
									#i check both the description and 
									#the imei because there're a lot of
									#fishy phones that pick IMEIs at random
									#but not too many that pick both IMEIs
									#and make/models at random.
									if ($modem_imei eq $imei and $modem_description eq $description) {	
										$modem_seen++;
										$modem_iface->Enable(0);
										$success++;
										last;
									}
								}
							}

						};

						if ($@) {
							print STDERR "Could not disconnect modem $modem: $@\n";
						}

						#update modem DB
						elsif ($success) {
							my $prep_stmt9 = $con->prepare("UPDATE modems SET enabled=0 WHERE id=? LIMIT 1");
							
							if ($prep_stmt9) {
								my $rc = $prep_stmt9->execute($modem);
								if ($rc) {
									$con->commit();
								}
								else {
									$success = 0;
									print STDERR "Could not execute UPDATE modems: ", $con->errstr, $/;
								}
							}
							else {
								print STDERR "Could not prepare UPDATE modems: ", $con->errstr, $/;
							}

								#log modem disconnect
								my @today = localtime;	
								my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
							
								open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

	      	 						if ($log_f) {

       									@today = localtime;	
									my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
									flock ($log_f, LOCK_EX) or print STDERR "Could not log modem disconnect for 1 due to flock error: $!$/";
									seek ($log_f, 0, SEEK_END);
									
									print $log_f "1 MODEM DISCONNECT $modem $time\n";	

									flock ($log_f, LOCK_UN);
       									close $log_f;
       								}
								else {
									print STDERR "Could not log disconnect modem for 1: $!\n";
								}
						}

						$header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/message.cgi">Send Messages</a> --&gt; <a href="/cgi-bin/message.cgi?act=view_modem&modem=$modem">View Modem</a>
	<hr> 
};

						$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Messenger - Send Messages - Disconnect Modem</title>
</head>

<body>
$header
*;
						if ($success) {
							$content .=
qq*
<p><span style="color: green">Modem successfully disconnected!</span>
*;
						}
						#modem has to have been seen--actually no.
						elsif($modem_seen) {
							$content .=
qq*
<p><span style="color: red">Could not disconnect modem.</span> Would you like to <a href="/cgi-bin/message.cgi?act=disconnect_modem&disconnect_stage=1&modem=$modem">retry</a>?
*;
						}

						#modem disconnected	
						else {
							$content .=
qq*
<p><span style="color: red">Could not disconnect modem.</span> Perhaps the modem has already been unplugged.
*;
						}

						$content .=
qq*
</body>
</html>
*;
					}
				}
			}

			#no such modem
			else {
				$feedback = qq!<p><span style="color: red">The modem selected for disconnection does not exist.</span>!;
				undef $act;
			}
		}
		else {
			$feedback = qq!<p><span style="color: red">No modem selected for disconnection.</span>!;
			undef $act;
		}
	}

	elsif (defined $act and $act eq "connect_modem") {
		if (defined $modem) {
			#ensure this modem is in the DB
			my ($imei,$description,$enabled) = (undef, undef, 0);

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my $prep_stmt6 = $con->prepare("SELECT imei,description FROM modems WHERE id=? LIMIT 1");
			
			if ($prep_stmt6) {
				my $rc = $prep_stmt6->execute($modem);

				if ($rc) {
					while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
						$imei = $rslts[0];
						$description = $rslts[1];	
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
				}	
			}
			else {
				print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
			}
		
			#found this modem
			if ( defined $imei ) {
				#use DBus too look up all modems
				#enable the one with a matching imei & description

				use Net::DBus;

				my ($modem_seen,$success) = (0,0);
				my $locked = "";
				my $enabled_status = 1;

				#wrapped in an eval--DBus/ModemManager
				eval {
					my $bus = Net::DBus->system;	
					my $modem_manager = $bus->get_service("org.freedesktop.ModemManager");

					#$content = dbus_dump($modem_manager);

					my $get_list = $modem_manager->get_object("/org/freedesktop/ModemManager", "org.freedesktop.ModemManager");
					my $list_modems = $get_list->EnumerateDevices();
							 
					#there're some modems attached
					if (ref($list_modems) eq "ARRAY") {
		
						for my $modem_name (@{$list_modems}) {
							
							my $modem_obj = $modem_manager->get_object($modem_name);
							my $props_iface = $modem_obj->as_interface("org.freedesktop.DBus.Properties");	

							my $modem_iface = $modem_obj->as_interface("org.freedesktop.ModemManager.Modem");

							my @description_bts = @{$modem_iface->GetInfo()};
							my $modem_description = uc("$description_bts[0] $description_bts[1]");
							my $modem_imei = $props_iface->Get("org.freedesktop.ModemManager.Modem", "EquipmentIdentifier");

							#same modem
							#i check both the description and 
							#the imei because there're a lot of
							#fishy phones that pick IMEIs at random
							#but not too many that pick both IMEIs
							#and make/models at random.
							if ($modem_imei eq $imei and $modem_description eq $description) {	
								$modem_seen++;
								$locked = $props_iface->Get("org.freedesktop.ModemManager.Modem", "UnlockRequired");
								
								#can only enable a modem that
								#doesn't require PINs etc
								if ($locked eq "") {
									$modem_iface->Enable(1);
								}
								else {
									$enabled_status = 0;
								}
								$success++;
								last;
							}
						}
					}
				};

				#log error
				if ($@) {
					print STDERR "Could not connect modem $modem: $@\n";
				}

				#update modem DB
				elsif ($success) {
					my $prep_stmt9 = $con->prepare("UPDATE modems SET enabled=?,locked=? WHERE id=? LIMIT 1");
							
					if ($prep_stmt9) {
						my $rc = $prep_stmt9->execute($enabled_status, $locked, $modem);
						if ($rc) {
							$con->commit();
						}
						else {
							$success = 0;
							print STDERR "Could not execute UPDATE modems: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare UPDATE modems: ", $con->errstr, $/;
					}

					#log modem disconnect
					my @today = localtime;	
					my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
							
					open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

					if ($log_f) {

       						@today = localtime;	
						my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
						flock ($log_f, LOCK_EX) or print STDERR "Could not log modem connect for 1 due to flock error: $!$/";
						seek ($log_f, 0, SEEK_END);
									
						print $log_f "1 MODEM CONNECT $modem $time\n";	

						flock ($log_f, LOCK_UN);
       						close $log_f;

       					}
					else {
						print STDERR "Could not log connect modem for 1: $!\n";
					}
				}

				#if modem connected, send user to view_modem otherwise show
				#an error msg
				if (not $success) {
					$header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/message.cgi">Send Messages</a> --&gt; <a href="/cgi-bin/message.cgi?act=view_modem&modem=$modem">View Modem</a>
	<hr> 
};

					$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Messenger - Send Messages - Connect Modem</title>
</head>

<body>
$header
<p><span style="color: red">Could not connect modem.</span> Would you like to <a href="/cgi-bin/message.cgi?act=connect_modem&modem=$modem">retry</a>?
</body>
</html>
*;
				}
				#allow user to view modem
				else {
					$act = "view_modem";
				}
			}
			#no such modem
			else {
				$feedback = qq!<p><span style="color: red">The modem selected for connection does not exist.</span> A new modem is added during creation of messaging jobs.!;
				undef $act;
			}

		}
		else {
			$feedback = qq!<p><span style="color: red">No modem selected for connection.</span>!;
			undef $act;
		}
	}

	if (defined $act and $act eq "view_modem") {
	
		if (defined $modem) {

			my ($imei,$description,$signal_quality,$access_tech,$status,$service_provider,$locked,$enabled) = (undef, undef, undef, undef, undef, undef, undef, undef);

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my $prep_stmt5 = $con->prepare("SELECT imei,description,signal_quality,access_tech,status,service_provider,locked,enabled FROM modems WHERE id=? LIMIT 1");
			
			if ($prep_stmt5) {
				my $rc = $prep_stmt5->execute($modem);

				if ($rc) {
					while ( my @rslts = $prep_stmt5->fetchrow_array() ) {
						$imei = $rslts[0];
						$description = htmlspecialchars($rslts[1]);
						$signal_quality = $rslts[2];
						$access_tech = $rslts[3];
						$status = $rslts[4];
						$service_provider = $rslts[5];
						$locked = $rslts[6];
						$enabled = $rslts[7];
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
				}	
			}
			else {
				print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
			}
		
				
			#no such modem
			if ( defined $imei ) {
				my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/message.cgi">Send Messages</a> --&gt; <a href="/cgi-bin/message.cgi?act=view_modem&modem=$modem">View Modem</a>
	<hr> 
};

				if (length($locked) > 0) {

						my %locked_lookup = 
(
"sim-pin" => "SIM PIN", 
"sim-puk" => "SIM PUK",
"ph-sim-pin" => "Phone-to-SIM PIN",
"ph-fsim-pin" => "Phone-to-very first SIM PIN",
"ph-fsim-puk" => "Phone-to-very first SIM card PUK",
"sim-pin2" => "SIM PIN 2",
"sim-puk2" => "SIM PUK 2",
"ph-net-pin" => "Network Personalization PIN",
"ph-net-puk" => "Network Personalization Unblocking PIN",
"ph-netsub-pin" => "Network Subset Personalization PIN",
"ph-netsub-puk" => "Network Subset Personalization PUK",
"ph-sp-pin" => "Service Provider Personalization PIN",
"ph-sp-puk" => "Service Provider Personalization PUK",
"ph-corp-pin" => "Corporate Personalization PIN",
"ph-corp-puk" => "Corporate Personalization PUK"
);
						my $code_request = qq!<TR><TD><LABEL for="code_1">$locked_lookup{$locked}</LABEL><TD><INPUT type="password" name="code_1" value="" size="10">!;

						my $unlock_type = "pin";
	
						if ( $locked =~ /\-puk/ ) {

							my $assoc_pin = $locked;
							$assoc_pin =~ s/puk/pin/;

							if (exists $locked_lookup{$assoc_pin}) {
								$unlock_type = "puk";
								$code_request .= qq!<TR><TD><LABEL for="code_2">NEW $locked_lookup{$assoc_pin}</LABEL><TD><INPUT type="password" name="code_2" value="" size="10">!;
								$code_request .= qq!<TR><TD><LABEL for="code_3">Confirm NEW $locked_lookup{$assoc_pin}</LABEL><TD><INPUT type="password" name="code_3" value="" size="10">!;
							}
						}

						$code_request .= qq!<INPUT type="hidden" name="unlock_type" value="$unlock_type">!;

						my $conf_code = gen_token();
						$session{"confirm_code"} = $conf_code;
						$code_request .= qq!<INPUT type="hidden" name="confirm_code" value="$conf_code">!;

						my $form =
qq*
<P>
<FORM method="POST" action="/cgi-bin/message.cgi?act=unlock_modem&modem=$modem">
<TABLE>
$code_request
<TR><TD colspan="2"><INPUT type="submit" name="unlock" value="Unlock">
</TABLE>
</FORM>
*;
						$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>

<title>Messenger - Send Messages - View Modem</title>

</head>

<body onload="init()">
$header
$feedback
<h3>$description (IMEI: $imei)</h3>
<span style="color: red">This modem is currently locked.</span>
$form
</body>
</html>
*;

					}
				else {
					if ($enabled) {	

						my $num_new_msgs = 0;

						my $prep_stmt4 = $con->prepare("SELECT COUNT(message_id) FROM inbox WHERE modem=? AND message_read !=2 LIMIT 1");

						if ( $prep_stmt4 ) {

							my $rc = $prep_stmt4->execute($modem);
							if ($rc) {
								while ( my @rslts = $prep_stmt4->fetchrow_array() ) {
									$num_new_msgs = $rslts[0];
								}
							}
							else {
								print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr, $/;
						}

						my $num_unread_msgs = "";

						if ($num_new_msgs > 0) {
							$num_unread_msgs = "($num_new_msgs)";
						}

						my %access_tech_lookup =
(
0 => "Unknown",
1 => "GSM",
2 => "Compact GSM",
3 => "GPRS",
4 => "EDGE",
5 => "UMTS",
6 => "HSDPA",
7 => "HSUPA",
8 => "HSPA",
9 => "HSPA PLUS",
10 => "LTE"
);
						my %status_lookup =
(
0 => qq!<span id="status" style="color: red">Idle</span>!,
1 => qq!<span id="status" style="color: green">Home</span>!,
2 => qq!<span id="status" style="color: grey">Searching</span>!,
3 => qq!<span id="status" style="color: red">Denied</span>!,
4 => qq!<span id="status" style="color: red">Unknown</span>!,
5 => qq!<span id="status" style="color: olive">Roaming</span>!,
);
				
						$content = 
qq*
<!DOCTYPE html>
<html lang="en">

<head>

<script type="text/javascript">

var httpRequest;
var waiting = 0;
var cntr = 0;
var num_re = /^[0-9]+\$/;
var new_msgs_cnt = $num_new_msgs;

var access_tech_lookup = [
{id: 0, value: "Unknown"},
{id: 1, value: "GSM"},
{id: 2, value: "Compact GSM"},
{id: 3, value: "GPRS"},
{id: 4, value: "EDGE"},
{id: 5, value: "UMTS"},
{id: 6, value: "HSDPA"},
{id: 7, value: "HSUPA"},
{id: 8, value: "HSPA"},
{id: 9, value: "HSPA PLUS"},
{id: 10, value: "LTE"}
];

var status_lookup = [
{id: 0, color: "red", descr: "Idle"},
{id: 1, color: "green", descr: "Home"},
{id: 2, color: "grey", descr: "Searching"},
{id: 3, color: "red", descr: "Denied"},
{id: 4, color: "red", descr: "Unknown"},
{id: 5, color: "olive", descr: "Roaming"}
];

var url = '';
function change_signal(signal_quality) {

	//clear
	for ( var k = 1; k < 5; k++ ) {
		for ( var l = 1; l < 5; l++ ) {
			if (l % 2 != 0) {
				document.getElementById(k + "." + l).outerHTML = "<td id='" + k + "." + l + "' bgcolor='white' style='border: 1px dotted; border-top: hidden; border-bottom: hidden'>";
			}
			else {
				document.getElementById(k + "." + l).outerHTML = "<td id='" + k + "." + l + "' bgcolor='white' style='border: hidden'>";
			}
		}
	}

	var signal_bars = Math.round(signal_quality / 25);
 
	if (signal_bars > 0) {
		
		switch (signal_bars) {
			case 4:
				for (var i = 1; i < 5; i++) {	
					document.getElementById(i + ".4").outerHTML = "<td id='" + i + ".4' bgcolor='black' style='border: hidden'>";
				}
			case 3:
				for (var j = 2; j < 5; j++) {
					document.getElementById(j + ".3").outerHTML = "<td id='" + j + ".3' bgcolor='black' style='border: 1px dotted; border-top: hidden; border-bottom: hidden'>";
				}
			case 2:
				for (var m = 3; m < 5; m++) {
					document.getElementById(m + ".2").outerHTML = "<td id='" + m + ".2' bgcolor='black' style='border: hidden'>";
				}
			case 1:
				document.getElementById("4.1").outerHTML = "<td id='4.1' bgcolor='black' style='border: 1px dotted; border-top: hidden; border-bottom: hidden'>";
		}
	}
	document.getElementById("sig_quality").innerHTML = signal_quality;

}

function reload() {
	
	if (httpRequest) {

		if (waiting) {
			return;	
		}

		waiting = 1;

		httpRequest.open('GET', url + '/cgi-bin/message.cgi?modem=$modem&act=refresh_modem&cntr=' + (++cntr) , false);
		httpRequest.setRequestHeader('Content-Type', 'text/plain');
		httpRequest.setRequestHeader('Cache-Control', 'no-cache');
		httpRequest.send();
		
		if (httpRequest.status === 200) {

			var result_txt = httpRequest.responseText;
	
			var bts = result_txt.split("#");

			if ( bts.length == 5 && bts[0].match(num_re) ) {

				var signal_quality = bts[0];
				var new_access_tech = bts[1];
				var new_status = bts[2];
				var new_service_provider = bts[3];
				var num_new_msgs = parseInt(bts[4]);

				change_signal(signal_quality);
	
				for (var i = 0; i < access_tech_lookup.length; i++) {
					if (access_tech_lookup[i].id == new_access_tech) {
						document.getElementById("access_tech").innerHTML = access_tech_lookup[i].value;
						break;
					}
				}

				for (var j = 0; j < status_lookup.length; j++) {
					if (status_lookup[j].id == new_status) {
						document.getElementById("status").innerHTML = status_lookup[j].descr;
						document.getElementById("status").style.color = status_lookup[j].color;
					}
				}

				document.getElementById("service_provider").innerHTML = new_service_provider;
				new_msgs_cnt += num_new_msgs;
				
				if (num_new_msgs > 0) {
					document.getElementById("num_unread_msgs").innerHTML = "(" + new_msgs_cnt + ")";
				}
			}
		}

		waiting = 0;
	}
}

function init() {

	change_signal($signal_quality);

	if (window.XMLHttpRequest) { 
		httpRequest = new XMLHttpRequest();
	}
	else if (window.ActiveXObject) {
		try {
			httpRequest = new ActiveXObject("Msxml2.XMLHTTP");
		}
		catch (e) {
			try {
				httpRequest = new ActiveXObject("Microsoft.XMLHTTP");
			}
			catch (e) {}
		}
	}

	window.setInterval(reload, 5000);

	url = window.location.protocol + '//' + window.location.hostname;	
}
</script>

<title>Messenger - Send Messages - Modems</title>
</head>

<body onload="init()">

$header
$feedback

<table border="1">

<tr>
<td style="font-weight: bold">Manufacturer/Model
<td>$description

<tr>
<td style="font-weight: bold">IMEI
<td>$imei

<tr>
<td style="font-weight: bold">Service Provider
<td><span id="service_provider">$service_provider</span>

<tr>
<td style="font-weight: bold">Status
<td>$status_lookup{$status}

<tr>
<td style="font-weight: bold">Access Technology
<td><span id="access_tech">$access_tech_lookup{$access_tech}</span>

</table>

<p><table border="1" cellpadding="3%" cellspacing="0">

<tr>
<td style="font-weight: bold" rowspan="5">Signal Quality (<span id="sig_quality">$signal_quality</span>)%

<tr>
<td id="1.1" style="border: 1px dotted; border-top: hidden; border-bottom: hidden">
<td id="1.2" style="border: hidden">
<td id="1.3" style="border: 1px dotted; border-top: hidden; border-bottom: hidden">
<td id="1.4" style="border: hidden">

<tr>
<td id="2.1" style="border: 1px dotted; border-top: hidden; border-bottom: hidden">
<td id="2.2" style="border: hidden">
<td id="2.3" style="border: 1px dotted; border-top: hidden; border-bottom: hidden">
<td id="2.4" style="border: hidden">

<tr>
<td id="3.1" style="border: 1px dotted; border-top: hidden; border-bottom: hidden">
<td id="3.2" style="border: hidden">
<td id="3.3" style="border: 1px dotted; border-top: hidden; border-bottom: hidden">
<td id="3.4" style="border: hidden">

<tr>
<td id="4.1" style="border: 1px dotted; border-top: hidden; border-bottom: hidden">
<td id="4.2" style="border: hidden">
<td id="4.3" style="border: 1px dotted; border-top: hidden; border-bottom: hidden">
<td id="4.4" style="border: hidden">
</table>

<p><a href="/cgi-bin/message.cgi?act=disconnect_modem&disconnect_stage=1&modem=$modem">Disconnect Modem</a>
<hr>
<h3><a href="/cgi-bin/message.cgi?act=view_inbox&modem=$modem">Inbox<span id="num_unread_msgs" style="font-weight: bold">$num_unread_msgs</span></a><h3>
<h3><a href="/cgi-bin/message.cgi?act=ussd_request&ussd_stage=1&modem=$modem">USSD Request</a></h3>
<h3><a href="/cgi-bin/message.cgi?act=send_message&modem=$modem">Create Message</a></h3>

</body>

</html>
*;
	
					}
					else {
						$content = 
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Messenger - Send Messages - Modems</title>
</head>

<body>
$header
$feedback
<h3>$description - (IMEI: $imei)</h3>
<span style="color: red">This modem is currently disabled.</em></span> Would you like to <a href="/cgi-bin/message.cgi?act=connect_modem&modem=$modem">enable it</a>?
</body>

</html>
*;
					}
				}
			}
			#no such modem
			else {
				$feedback = qq!<p><span style="color: red">The modem selected does not exist.</span>!;
				undef $act;
			}
		}
		#no modem selected
		else {
			$feedback = qq!<p><span style="color: red">No modem selected.</span>!;
			undef $act;
		}
	}

	if ($act eq "view_job") {

		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

		my $space = " ";
		my ($job_name, $modem, $msg_validity, $num_msgs, $num_delivered,$job_start, $last_activity, $instructions, $recent_activity) = (undef, undef, undef, undef, undef, undef, undef, undef, undef);

		my $prep_stmt1 = $con->prepare("SELECT name,modem,message_validity,number_messages,number_delivered,job_start,last_activity,instructions,recent_activity FROM messaging_jobs WHERE id=? LIMIT 1");

		if ($prep_stmt1) {
			my $rc = $prep_stmt1->execute($job);
			if ($rc) {
				while ( my @rslts = $prep_stmt1->fetchrow_array() ) {

					$job_name = $rslts[0];	
					$job_name =~ s/\x2B/$space/ge;
					$job_name =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
					$job_name = htmlspecialchars($job_name);

					$modem = $rslts[1];
					$msg_validity = $rslts[2];
					$num_msgs = $rslts[3];
					$num_delivered = $rslts[4];
					$job_start = $rslts[5];
					$last_activity = $rslts[6];
					$instructions = $rslts[7];
					$recent_activity = $rslts[8];
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM messaging_jobs: ", $con->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM messaging_jobs: ", $con->errstr, $/;
		}

		if ( not defined $job_name ) {
			$job = undef;
		}

		if ( defined $job ) {
	
			my $is_active = 1;
			my $done = 0;

			my $time = time;
			#expired
			if ( ($job_start + $msg_validity) < $time ) {
				$is_active = 0;	
			}

			#always want this 2 b tested.
			#all msgs have been sent
			if ($num_delivered >= $num_msgs) {
				$is_active = 0;
				$done++;	
			}
			#job was manually stopped?
			elsif ($instructions == 2) {
				$is_active = 0;	
			}

			my $suspend = "";
			#opt to suspend
			if ($is_active == 1) {
				$suspend = qq!<p><a href="/cgi-bin/message.cgi?act=suspend_job&job=$job">Suspend Job</a>!;
			}
			else {
				$suspend = qq!<p>!;
				unless ( $done ) {
					$suspend .= qq!<a href="/cgi-bin/message.cgi?act=resume_job&job=$job">Resume Job</a>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;!;
				}
				$suspend .= qq!<a href="/cgi-bin/message.cgi?act=restart_job&job=$job">Restart Job</a>!;
			}

			my ($imei, $description, $enabled) = (undef, undef, undef);

			my $prep_stmt2 = $con->prepare("SELECT imei,description,enabled FROM modems WHERE id=? LIMIT 1");

			if ($prep_stmt2) {

				my $rc = $prep_stmt2->execute($modem);
				if ($rc) {
					while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
						$imei = $rslts[0];
						$description = $rslts[1];
						$enabled = $rslts[2];
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
			}

			my $modem_style = qq! style="color: gray"!;
			my $modem_str = "No Modem";

			if (defined $imei) {
				if ($enabled) {
					$modem_style = "";
				}
				$modem_str = qq!<a href="/cgi-bin/message.cgi?act=view_modem&modem=$modem">$description\[$imei\]</a>!;
			}

			my ($sms_rate_row, $estimated_time_row) = ("", "");

			

			if ($is_active) {

				#get per min, estimate remaining
				my ($min,$max,$sent) = (0,0,0);

				my $prep_stmt3 = $con->prepare("SELECT min(sent),max(sent),count(message_id) FROM outbox WHERE messaging_job=? AND sent > 0 LIMIT 1");
			
				if ($prep_stmt3) {

					my $rc = $prep_stmt3->execute($job);
					if ($rc) {
						while ( my @rslts = $prep_stmt3->fetchrow_array() ) {
							$min  = $rslts[0];
							$max  = $rslts[1];
							$sent = $rslts[2];
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
				}

				$sms_rate_row = qq!<TR><TH>Rate</TH><TD><span id="sms_rate">0</span> SMSs/min</TD>!;
				$estimated_time_row = qq!<TR><TH>Estimated Time Remaining:</TH><TD><span id="remaining_time">Unknown</span> mins</TD>!;

				#some msgs have been sent
				if ($min and $max) {

					my $rate = sprintf("%.1f", (60 / ( ($max - $min) / $sent )) );
					my $sms_rate = qq!<span id="sms_rate">$rate</span> SMSs/min!;

					my $remaining_time = 0;
					if ( $rate > 0 ) {
						$remaining_time = sprintf( "%.1f", ($num_msgs - $num_delivered) / $rate );
					}

					my $estimated_time = qq!<span id="remaining_time">$remaining_time</span> mins!;
				
					$sms_rate_row = "<TR><TH>Rate:</TH><TD>$sms_rate</TD>";
					$estimated_time_row = "<TR><TH>Estimated Time Remaining:</TH><TD>$estimated_time</TD>";
				}	
			}

			#assume active, lively job
			my $status = qq!<span id="status">Running</span>!;
			#done
			if ($done) {
				$status = qq!<span id="status" style="color: green">Completed</span>!;
			}
			#suspended job
			elsif ( $instructions == 2 ) {
				$status = qq!<span id="status" style="color: red">Suspended</span>!;
			}
			#dead? job--last heard 30+ secs ago
			elsif ( ($last_activity + 30) < $time ) {
				$status = qq!<span id="status" style="color: gray">Defunct</span>!;
			}

			$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>

<SCRIPT type="text/javascript">

var httpRequest;
var waiting = 0;
var cntr = 0;
var num_re = /^[0-9]+\\.[0-9],[0-9]+\\.[0-9],[0-2]+\$/;

var url = '';
var dry_runs = 0;

function reload() {
	
	if (httpRequest) {

		if (waiting) {
			return;	
		}

		waiting = 1;

		httpRequest.open('GET', url + '/cgi-bin/message.cgi?act=refresh_job&job=$job&cntr=' + (++cntr) , false);
		httpRequest.setRequestHeader('Content-Type', 'text/plain');
		httpRequest.setRequestHeader('Cache-Control', 'no-cache');
		httpRequest.send();
		
		if (httpRequest.status === 200) {

			var result_txt = httpRequest.responseText;

			if ( result_txt.length > 0 ) {

				var new_line = result_txt.indexOf("\\n");

				if ( new_line >= 0 ) {

					var line1 = result_txt.substr(0, new_line);

					if ( line1.match(num_re) ) {

						var bts = line1.split(",");
						var recent_activity = result_txt.substr(new_line + 1);

						document.getElementById("sms_rate").innerHTML = bts[0];
						document.getElementById("remaining_time").innerHTML = bts[1];

						switch (bts[2]) {
							case "0":
								document.getElementById("status").innerHTML = "Defunct";
								document.getElementById("status").style.color = "gray";
								break;
							case "1":
								document.getElementById("status").innerHTML = "Running";
								document.getElementById("status").style.color = "";
								break;
							case "2":
								document.getElementById("status").innerHTML = "Done";
								document.getElementById("status").style.color = "green";
						}
						document.getElementById("recent_activity").innerHTML = recent_activity;
						dry_runs = 0;
					}
					else {
						dry_runs++;
					}
				}
				else {
					dry_runs++;
				}

			}
			else {
				dry_runs++;
			}
		}
		else {
			dry_runs++;
		}

		if ( dry_runs > 7 ) {
			document.getElementById("status").innerHTML = "Defunct";
			document.getElementById("status").style.color = "gray";	
		}
		waiting = 0;	
	}

}

function init() {

	if (window.XMLHttpRequest) { 
		httpRequest = new XMLHttpRequest();
	}
	else if (window.ActiveXObject) {
		try {
			httpRequest = new ActiveXObject("Msxml2.XMLHTTP");
		}
		catch (e) {
			try {
				httpRequest = new ActiveXObject("Microsoft.XMLHTTP");
			}
			catch (e) {}
		}
	}

	window.setInterval(reload, 5000);

	url = window.location.protocol + '//' + window.location.hostname;	
}

</SCRIPT>
<title>Messenger - Send Messages - View Messaging Job</title>

</head>

<body onload="init()">
$header
$feedback
$suspend
<hr>

<TABLE style="text-align: left">

<TR><TH>Job Name:</TH><TD>$job_name</TD>
<TR><TH>Modem:</TH><TD$modem_style>$modem_str</TD>
$sms_rate_row
$estimated_time_row
<TR><TH>Status:</TH><TD>$status</TD>
</TABLE>

<h4>Most Recent Activity</h4>
<div id="recent_activity">
$recent_activity
</div>

<p><a target="_blank" href="/cgi-bin/message.cgi?act=view_job_messages&job=$job">View all messages</a>
</body>

</html>
*;	
		}
		else {
			$feedback = qq!<span style="color: red">No job selected.</span> Select one of the jobs listed.!;
			$act = undef;
		}
	}

	#display current jobs
	if (not defined $act and not defined $job) {

		$session{"job_name"} = "";
		$session{"modem"} = "";
		$session{"modem_path"} = "";
		$session{"datasets"} = "";
		$session{"message_template"} = "";
		$session{"message_validity"} = "";
		$session{"db_filter_type"} = "";
		$session{"db_filter"} = "";
	
		my $jobs_table = "<p><em>No messaging jobs have been created yet.</em>";
		my %current_jobs = ();
		my $space = " ";

		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

		my $prep_stmt1 = $con->prepare("SELECT id,name,modem,number_messages,number_delivered,job_start,last_activity,instructions FROM messaging_jobs WHERE pid IS NOT NULL ORDER BY id ASC");

		if ($prep_stmt1) {
			my $rc = $prep_stmt1->execute();
			if ($rc) {
				while ( my @rslts = $prep_stmt1->fetchrow_array() ) {

					my $job_name = $rslts[1];					
					$job_name =~ s/\x2B/$space/ge;
					$job_name =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
					$job_name = htmlspecialchars($job_name);


					$current_jobs{$rslts[0]} = {"name" => $job_name,"modem_id" => $rslts[2], "number_messages" => $rslts[3], "number_delivered" => $rslts[4], "job_start" => $rslts[5], "last_activity" => $rslts[6], "instructions" => $rslts[7]}; 
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM messaging_jobs: ", $con->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM messaging_jobs: ", $con->errstr, $/;
		}

		my $js_msgs_str = '[]';
		#read modem data

		if (keys %current_jobs) {
	
			my %modems;

			my $prep_stmt2 = $con->prepare("SELECT id,imei,description,enabled FROM modems WHERE id=? LIMIT 1");
			
			if ($prep_stmt2) {
				for my $job ( keys %current_jobs ) {
					my $modem_id = ${$current_jobs{$job}}{"modem_id"};

					#perhaps this modem is shared btn jobs.
					next if (exists $modems{$modem_id});
					
					my $rc = $prep_stmt2->execute($modem_id);

					if ($rc) {
						while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
							$modems{$rslts[0]} = { "imei" => $rslts[1], "description" => $rslts[2], "enabled" => $rslts[3] };
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM modems: ", $con->errstr, $/;
					}		
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM modems: ", $con->errstr,$/;
			}

			$jobs_table =
qq!
<TABLE border="1">
<THEAD>
<TH>Name
<TH>Modem
<TH>Number of Messages
<TH>Number Delivered
<TH>Job Start
<TH>Last Activity
</THEAD>
<TBODY>
!;
			my @js_msgs = ();	

			for my $job ( keys %current_jobs ) {

				my $modem = qq!<TD style="color: grey"><span id="job_${job}_modem">No Modem</span>!;

				my $modem_id = ${$current_jobs{$job}}{"modem_id"};

				if (exists $modems{$modem_id}) {

					$modem = "<TD>";
					#modem disabled
					if ( ${$modems{$modem_id}}{"enabled"} == 0 ) {
						$modem = qq!<TD style="color: grey">!;
					}
					
					$modem .= qq!<a href="/cgi-bin/message.cgi?act=view_modem&modem=$modem_id"><span id="job_${job}_modem">${$modems{$modem_id}}{"description"}\[${$modems{$modem_id}}{"imei"}\]</span></a>!;
				}

				my $job_name = htmlspecialchars(${$current_jobs{$job}}{"name"});
				my $start_time = custom_time(${$current_jobs{$job}}{"job_start"});
				my $last_activity = custom_time(${$current_jobs{$job}}{"last_activity"});

				
				my $num_msgs = ${$current_jobs{$job}}{"number_messages"};
				my $num_delivered = ${$current_jobs{$job}}{"number_delivered"};

				#if done, display last activity as a date
				#because no updates expected.
				if ($num_delivered >= $num_msgs) {

					my @time_bts = localtime(${$current_jobs{$job}}{"job_start"});
					$start_time = sprintf ("%02d/%02d/%d %02d:%02d:%02d", $time_bts[3], ($time_bts[4] + 1), ($time_bts[5] + 1900),  $time_bts[2], $time_bts[1], $time_bts[0]);

					@time_bts = localtime(${$current_jobs{$job}}{"last_activity"});
					$last_activity = sprintf ("%02d/%02d/%d %02d:%02d:%02d", $time_bts[3], ($time_bts[4] + 1), ($time_bts[5] + 1900),  $time_bts[2], $time_bts[1], $time_bts[0]);
				}

				my $done = "false";
				if ($num_delivered >= $num_msgs) {
					$done = "true";
				}

				my $row_style = "";
				if ( ${$current_jobs{$job}}{"instructions"} == 2 ) {
					#grey out stopped/suspended jobs
					$row_style = qq! style="color: gray"!
				}

				$jobs_table .= qq!<TR$row_style><TD><a href="/cgi-bin/message.cgi?act=view_job&job=$job"><span id="job_${job}_name">$job_name</span></a>$modem<TD><span id="job_${job}_num_msgs">$num_msgs</span><TD><span id="job_${job}_num_delivered">$num_delivered</span><TD><span id="job_${job}_start">$start_time</span><TD><span id="job_${job}_last_activity">$last_activity</span>!;

				push @js_msgs, qq!{job: $job, num_msgs: $num_msgs, done: $done, last_refresh: 0}!;
			}
			
			$jobs_table .= "</TBODY></TABLE>";
			$js_msgs_str = '[' . join(", ", @js_msgs) . ']';
		}
		$content .=
qq*
<!DOCTYPE html>
<html lang="en">

<head>

<SCRIPT type="text/javascript">

var httpRequest;
var waiting = 0;
var cntr = 0;
var num_re = /^[0-9]+\$/;

var url = '';
var msgs = $js_msgs_str;

function reload() {
	
	if (httpRequest) {

		if (waiting) {
			return;	
		}

		waiting = 1;

		httpRequest.open('GET', url + '/cgi-bin/message.cgi?act=refresh&cntr=' + (++cntr) , false);
		httpRequest.setRequestHeader('Content-Type', 'text/plain');
		httpRequest.setRequestHeader('Cache-Control', 'no-cache');
		httpRequest.send();
		
		if (httpRequest.status === 200) {

			var result_txt = httpRequest.responseText;
			var rows = result_txt.split("\$");
		
			for (var i = 0; i < rows.length; i++) {

				var bts = rows[i].split("#");

				if ( bts.length == 3 && bts[0].match(num_re) ) {

					var job = bts[0];
					var num_delivered = bts[1];
					var last_activity = bts[2];

					document.getElementById("job_" + job + "_num_delivered").innerHTML = num_delivered;
					document.getElementById("job_" + job + "_last_activity").innerHTML = last_activity;

					for (var j = 0; j < msgs.length; j++) {

						if (msgs[j].job == job) {

							msgs[j].last_refresh = cntr;

							if ( num_delivered >= msgs[j].num_msgs ) {	
								msgs[j].done = true;
							}

							break;
						}
					}
				}
			}
		}

		for (var j = 0; j < msgs.length; j++) {

			if ( msgs[j].done ) {

				document.getElementById("job_" + msgs[j].job + "_name").style.color = "green";
				document.getElementById("job_" + msgs[j].job + "_modem").style.color = "green";
				document.getElementById("job_" + msgs[j].job + "_num_msgs").style.color = "green";
				document.getElementById("job_" + msgs[j].job + "_num_delivered").style.color = "green";
				document.getElementById("job_" + msgs[j].job + "_start").style.color = "green";
				document.getElementById("job_" + msgs[j].job + "_last_activity").style.color = "green";	
			}
			else {
				//document.getElementById("tst").innerHTML += "job " + msgs[j].job + " is NOT done.<BR>";

				if ( (cntr - msgs[j].last_refresh) > 5) {
					document.getElementById("job_" + msgs[j].job + "_name").style.color = "red";
					document.getElementById("job_" + msgs[j].job + "_modem").style.color = "red";

					document.getElementById("job_" + msgs[j].job + "_num_msgs").style.color = "red";
					document.getElementById("job_" + msgs[j].job + "_num_delivered").style.color = "red";
					document.getElementById("job_" + msgs[j].job + "_start").style.color = "red";
					document.getElementById("job_" + msgs[j].job + "_last_activity").style.color = "red";
				}
			}	
		}
		waiting = 0;
	}
}

function init() {

	if (window.XMLHttpRequest) { 
		httpRequest = new XMLHttpRequest();
	}
	else if (window.ActiveXObject) {
		try {
			httpRequest = new ActiveXObject("Msxml2.XMLHTTP");
		}
		catch (e) {
			try {
				httpRequest = new ActiveXObject("Microsoft.XMLHTTP");
			}
			catch (e) {}
		}
	}

	window.setInterval(reload, 10000);

	url = window.location.protocol + '//' + window.location.hostname;	
}
</SCRIPT>

<title>Messenger - Send Messages - List of Messaging Jobs</title>
</head>

<body onload='init()'>
$header
$feedback
$jobs_table
<p><a href="/cgi-bin/message.cgi?act=create_job&create_stage=1">Create New Job</a> 
<div id="tst"></div>
</body>

</html>
*;
	}
}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

sub custom_time {

	my $custom_time = "";

	my $time = $_[0];
	my $now = time;
	
	my $elapsed_time = $now - $time;
	
	#-ve elapsed time? this shouldn't happen...
	#but just being careful.
	#if less than a day has elapsed,
	#just give the minutes/secs/hrs passed
	if ( $elapsed_time >= 0 and $elapsed_time < 86400) {
		#seconds
		if ( $elapsed_time < 60 ) {
			$custom_time .= $elapsed_time . " sec ago";
		}
		#minutes
		elsif ( $elapsed_time < 3600 ) {

			my $minutes = int($elapsed_time / 60);
			my $seconds = $elapsed_time - ($minutes * 60);
	
			$custom_time .= $minutes ." min";

			if ($seconds > 0) {
				$custom_time .= ", " . $seconds . " sec";
			}
			$custom_time .= " ago";
		}
		#an hr+
		else {
			my $hrs = int ($elapsed_time / 3600);
			$elapsed_time -= ($hrs * 3600);

			my $minutes = int($elapsed_time / 60);
				
			$custom_time .= $hrs . ($hrs == 1 ? " hr" : " hrs");

			if ($minutes > 0) {
				$custom_time .= ", " . $minutes . " min";
			}
			
			$custom_time .= " ago";
		}
	}

	else {
		my @time_bts = localtime($time);

		$custom_time = sprintf ("%02d/%02d/%d %02d:%02d:%02d", $time_bts[3], ($time_bts[4] + 1), ($time_bts[5] + 1900),  $time_bts[2], $time_bts[1], $time_bts[0]);
	}
	return $custom_time;
}

sub grade_sort {
	#idea is to try & give the student
	#the best grade their marks can
	#earn. Presumably, higher marks == better grade

		
	#both have a minimum
	#use the higher of the 2
	if (exists ${$grading{$a}}{"min"} and exists ${$grading{$b}}{"min"}) {
		return ${$grading{$b}}{"min"} <=> ${$grading{$a}}{"min"};
	}
	#both have a maximum
	#use the higher of the 2
	elsif (exists ${$grading{$a}}{"max"} and exists ${$grading{$b}}{"max"}) {
		return ${$grading{$b}}{"max"} <=> ${$grading{$a}}{"max"};
	}
	elsif (exists ${$grading{$a}}{"eq"} and exists ${$grading{$b}}{"eq"}) {
		return ${$grading{$b}}{"eq"} <=> ${$grading{$a}}{"eq"};
	}
	#$a has eq, $b doesn't 
	if (exists ${$grading{$a}}{"eq"}) {
		return 1;
	}
	#$b has eq, $a doesn't
	else {
		return -1;
	}  

	#$a has a min set, $b doesn't 
	if (exists ${$grading{$a}}{"min"}) {
		return 1;
	}
	#$b has a min set, $a doesn't
	else {
		return -1;
	}
}

sub get_grade {
	my $grade = "";
	return "" unless (@_);
	my $score = $_[0];

	GRADE: for my $tst_grade (sort grade_sort keys %grading) {
		my %tst_conds = %{$grading{$tst_grade}};
		#check equality
		if (exists $tst_conds{"eq"}) {
			if ($score == $tst_conds{"eq"}) {
				$grade = $tst_grade;
				last GRADE;		
			}
		}
		elsif (exists $tst_conds{"min"}) {
			if ($score > $tst_conds{"min"}) {
				$grade = $tst_grade;
				last GRADE;		
			}
		}
		elsif (exists $tst_conds{"max"}) {
			if ($score < $tst_conds{"max"}) {
				$grade = $tst_grade;
				last GRADE;		
			}
		}
	}
	return $grade;
}


