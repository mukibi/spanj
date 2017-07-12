#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use CGI;

use Digest::SHA qw /sha1_hex/;
use Fcntl qw/:flock SEEK_END/;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d);
my $id;
my %session;
my $authd = 0;
my $confirmed = 0;
my $conf_code;
my $con;

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
	if (exists $session{"id"} and $session{"id"} =~ /^([A-Z0-9]+)$/) {
		$authd++;
		$id = $1;
	}
}

my @acts=("chusername", "chpass", "chsecqs", "chsysvars");
my $valid_req = 0;
my $req_act;

if ($authd) {
	my $valid_req = 0;
	if ( exists $ENV{"QUERY_STRING"} ) {
		if ($ENV{"QUERY_STRING"} =~ /\&?act=(.+)\&?/) {	
			$req_act = $1;
			$req_act = lc($req_act);
			foreach (@acts) {
				if ($req_act eq $_) {
					$valid_req = 1;	
					last;
				}
			}
		}
	}

	if ($valid_req) {
		my %auth_params;
		if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
			$confirmed++;
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
					$auth_params{$k} = $v;
				}
			}
		}
		my $token = gen_token();

		my $content = 
"<!DOCTYPE html>
<html lang='en'>
<head>
";
	#chusername request
	if ($req_act eq "chusername") {

		if ($confirmed) {
			if ( exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and ($session{"confirm_code"} eq $auth_params{"confirm_code"}) ) {
			if ( exists $auth_params{"n_uname"} and $auth_params{"n_uname"} =~ /^[A-Za-z0-9_\-\.\s]{1,16}$/ ) {
				my $nu_name = lc($auth_params{"n_uname"});
     				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
				my $succ_msg;
				if ($con) {
					my $prep_stmt = $con->prepare("UPDATE users SET u_name=? WHERE u_id=? LIMIT 1");
				
					if ($prep_stmt) {
						my $rc = $prep_stmt->execute($nu_name,$id);
						if ($rc) {
							$session{"name"} = $nu_name;
							my @new_sess_array;
							for my $sess_key (keys %session) {
								push @new_sess_array, $sess_key."=".$session{$sess_key};	
							}

							my $new_sess = join ('&',@new_sess_array);			
							print "X-Update-Session: $new_sess\r\n";

							my @today = localtime;
							my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

							open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        						if ($log_f) {
                						@today = localtime;	
								my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
								flock ($log_f, LOCK_EX) or print STDERR "Could not log change username for due to flock error: $!$/"; 
								seek ($log_f, 0, SEEK_END);
		 						print $log_f "$id CHANGE USERNAME $nu_name $time\n";
								flock ($log_f, LOCK_UN);
                						close $log_f;
        						}
							else {
								print STDERR "Could not log change username for $id: $!\n";
							}

							$succ_msg = "<h5>Your username has been updated to $nu_name!</h5><br>You should be redirected to <a href=\"/settings.html\">/settings.html</a> in <span style='font-weight: bold' id='counter'>11s</span>. If you are not, <a href=\"/settings.html\">Click Here</a>";
							 
						}
						else {
							print STDERR "Couldn't execute UPDATE users: ", $prep_stmt->errstr, $/;
						}
					}
					else {
						print STDERR "Couldn't prepare prepare UPDATE users: ", $prep_stmt->errstr, $/;  
					}
					$con->commit();
					$con->disconnect();
					not_found($succ_msg, 10);
					exit 0;
				}
				}
				else {
					my $error_msg = "<span style='color: red'>A valid username should be no more than 16 characters alphanumeric characters(A-Z, 0-9)</span>.<br>You should be redirected to <a href=\"/settings.html\">/settings.html</a> in <span style='font-weight: bold' id='counter'>11s</span>. If you are not, <a href=\"/settings.html\">Click Here</a>"; 
					not_found($error_msg, 10);
					exit 0;
				}
			}
			else {
					my $error_msg = "<span style='color: red'>Do not alter the tokens within the HTTP form</span>.<br>You should be redirected to <a href=\"/settings.html\">/settings.html</a> in <span style='font-weight: bold' id='counter'>11s</span>. If you are not, <a href=\"/settings.html\">Click Here</a>"; 
				not_found($error_msg, 10);
				exit 0;
			}
		}
		else {
			$session{"confirm_code"} = $token; 
			my @new_sess_array;
			for my $sess_key (keys %session) {
				push @new_sess_array, $sess_key."=".$session{$sess_key};	
			}
			my $new_sess = join ('&',@new_sess_array);
			
			print "X-Update-Session: $new_sess\r\n";

			$content .=

'<title>Spanj: Exam Management Information System- Change Username</title>
	<script>
		function confirm_change() {
			var u_name = "' . $session{"name"} . '";' .
			'var n_uname = document.getElementById("new_uname").value;
			var new_content =
			"<p><h5>Are you sure you want to change your username from <span style=\'color: red\'>' . $session{"name"} .'</span> to <span style=\'color: red\'>" + n_uname + "</span>?</h5>' . 
			'<form action=\'/cgi-bin/settings.cgi?act=chusername\' method=\'POST\'>'.
			'<input type=\'hidden\' name=\'n_uname\' value=\'" + n_uname + "\'>'.
			'<input type=\'hidden\' name=\'confirm_code\' value=\'' . $token .
			'\'>'.
			'<table>'.
			'<tr><td>'.
			'<input type=\'button\' name=\'cancel\' value=\'Cancel Change\' onclick=\'cancel_change()\'>'. 
			'<td>'.
			'<input type=\'submit\' name=\'Save\' value=\'Confirm Change\'>'.
			'</form>";'.
			'document.getElementById("pre_conf").innerHTML = new_content;
		}

		function cancel_change() {
			window.location.href = "/settings.html";
		}

	</script>
</head>

<body>

<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/settings.html">

	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/settings.html">Settings</a> --&gt; <a href="/cgi-bin/settings.cgi?act=chusername">Change Username</a> 
<div id="pre_conf"> 
	<h5>Current Username: admin</h5>
	<table>
	<tr>
	<td><label for="u_name">New Username</label>
	<td><input name="u_name" type="text" id="new_uname" value="" maxlength="16" size="16">
	<tr>
	<td><input type="button" value="Save" name="Change Username" onclick="confirm_change()">
	</table>
</div>

</body>
</html>
';
			}	
	}

		#chpass request
	elsif ($req_act eq "chpass") {
		
		if ($confirmed) {

			if ( exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and ($session{"confirm_code"} eq $auth_params{"confirm_code"}) ) {
			if ( exists $auth_params{"n_pwd"} and $auth_params{"n_pwd"} =~ /^.{6,}$/ ) {

				my $nu_pwd = $auth_params{"n_pwd"};
				my $nu_salt = substr(gen_token(), 0, 16);
				my $nu_pass_hash = uc( sha1_hex($nu_pwd . $nu_salt) );

     				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
				my $succ_msg;
				if ($con) {

					my $success = 1;
					#enc keys
					if ( $id =~ /^\d+$/ and ($id == 2 or $id % 17 == 0) ) {
						#only change pass after keys have been updated
						$success = 0;
						#read sess key
						if (exists $session{"sess_key"} ) {

							use MIME::Base64 qw /decode_base64/;

							my $decoded = decode_base64($session{"sess_key"});
							my @decoded_bytes = unpack("C*", $decoded);

							my @sess_init_vec_bytes = splice(@decoded_bytes, 32);
							my @sess_key_bytes = @decoded_bytes;

							#read enc_keys_mem
							my $prep_stmt3 = $con->prepare("SELECT init_vec,aes_key FROM enc_keys_mem WHERE u_id=? LIMIT 1");

							if ( $prep_stmt3 ) {

								my $rc = $prep_stmt3->execute($session{"id"});

								if ( $rc ) {

									my ($mem_init_vec, $mem_aes_key) = (undef,undef);
									while (my @rslts = $prep_stmt3->fetchrow_array()) {
										$mem_init_vec = $rslts[0];
										$mem_aes_key = $rslts[1];
									}

									if ( defined $mem_init_vec ) {

										my @mem_init_vec_bytes = unpack("C*", $mem_init_vec);
										my @mem_aes_key_bytes = unpack("C*", $mem_aes_key);

										my ( @decrypted_init_vec, @decrypted_aes_key );
	
										for (my $i = 0; $i < @mem_init_vec_bytes; $i++) {
											$decrypted_init_vec[$i] = $mem_init_vec_bytes[$i] ^ $sess_init_vec_bytes[$i];
										}

										for (my $j = 0; $j < @mem_aes_key_bytes; $j++) {
											$decrypted_aes_key[$j] = $mem_aes_key_bytes[$j] ^ $sess_key_bytes[$j];
										}

										my $key = pack("C*", @decrypted_aes_key);
										my $iv = pack("C*", @decrypted_init_vec);

										

										#reencrypt key
										#****#change PWD and SALT
										my $salt = $nu_salt;
										my $pwd = $nu_pwd;	

										use Crypt::PBKDF2;
										my $pbkdf2 = Crypt::PBKDF2->new(output_len => 32, salt_len => length($salt) + 1);

										my $pwd_key = $pbkdf2->PBKDF2($salt . "0", $pwd);

										my @pwd_key_bytes = unpack("C*", $pwd_key);
										my @key_bytes = @decrypted_aes_key;

										my @xord_key = ();

										for (my $i = 0; $i < scalar(@key_bytes); $i++) {
											$xord_key[$i] = $key_bytes[$i] ^ $pwd_key_bytes[$i];
										}

										my $pwd_iv = $pbkdf2->PBKDF2($salt . "1", $pwd);
										my @pwd_iv_bytes_0 = unpack("C*", $pwd_iv);
										my @pwd_iv_bytes = splice(@pwd_iv_bytes_0, 0, 16);
										my @iv_bytes = unpack("C*", $iv);

										my @xord_iv = ();
										for (my $i = 0; $i < scalar(@iv_bytes); $i++) {
											$xord_iv[$i] = $iv_bytes[$i] ^ $pwd_iv_bytes[$i];
										}

										my $nu_iv = pack("C*", @xord_iv);
										my $nu_key = pack("C*", @xord_key);

										
										my $prep_stmt4 = $con->prepare("UPDATE enc_keys SET init_vec=?, aes_key=? WHERE u_id=? LIMIT 1");
										if ($prep_stmt4) {
											my $rc = $prep_stmt4->execute($nu_iv, $nu_key, $id);
											unless ( $rc ) {
												print STDERR "Couldn't execute UPDATE enc_keys: ", $prep_stmt4->errstr, $/;		
											}
										}
										else {
											print STDERR "Couldn't prepare UPDATE enc_keys: ", $prep_stmt4->errstr, $/;
										}

										#generate session key
										#generate random key to
										#encrypt the keys during this session
										use Crypt::Random::Source qw/get_strong/;

										my $sess_key = get_strong(48);
										my @sess_key_bytes = unpack("C*", $sess_key);

										my @iv_reencd_bytes = splice(@sess_key_bytes, 32);
										my @key_reencd_bytes = @sess_key_bytes;

										my (@reencd_iv, @reencd_key);

										for (my  $i = 0; $i < scalar(@iv_bytes); $i++ ) {
											$reencd_iv[$i] = $decrypted_init_vec[$i] ^ $iv_reencd_bytes[$i];
										}

										for ( my $j = 0; $j < scalar(@key_bytes); $j++ ) {
											$reencd_key[$j] = $key_bytes[$j] ^ $key_reencd_bytes[$j];
										}

										my $encrypted_iv = pack("C*", @reencd_iv);
										my $encrypted_key = pack("C*", @reencd_key);
	
										
	
										#create table enc_keys_mem
										#MEMORY tables can be expected to
										#disappear at will.
										my $prep_stmt2 = $con->prepare("CREATE TABLE IF NOT EXISTS enc_keys_mem (u_id integer unique, init_vec binary(16),aes_key binary(32)) ENGINE=MEMORY");	
										if ( $prep_stmt2 ) {
											my $rc = $prep_stmt2->execute();
											if ($rc) {
												my $prep_stmt3 = $con->prepare("REPLACE INTO enc_keys_mem VALUES(?,?,?)");
												if ($prep_stmt3) {
													my $rc = $prep_stmt3->execute($id, $encrypted_iv, $encrypted_key);
													if ( $rc ) {
														use MIME::Base64 qw/encode_base64/;
														my $encoded_sess_key = encode_base64($sess_key, "");
														$session{"sess_key"} = $encoded_sess_key;

														
														$success = 1;
													}
													else {
														print STDERR "Could not execute INSERT INTO enc_keys_mem: ", $prep_stmt3->errstr, $/;  
													}
												}
												else {
													print STDERR "Could not prepare INSERT INTO enc_keys_mem: ", $prep_stmt3->errstr, $/;  
												}
											}
											else {
												print STDERR "Could not execute CREATE enc_keys_mem: ", $prep_stmt2->errstr, $/;  
											}
										}
										else {
											print STDERR "Could not prepare CREATE enc_keys_mem: ", $prep_stmt2->errstr, $/;  
										}

									}	
								}
								else {
									print STDERR "Couldn't execute SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
								}
							}
							else {
								print STDERR "Couldn't prepare SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
							}
						}
					}
					if ($success) {
					my $prep_stmt = $con->prepare("UPDATE users SET password=?, salt=? WHERE u_id=? LIMIT 1");
			
					if ($prep_stmt) {
						my $rc = $prep_stmt->execute($nu_pass_hash, $nu_salt, $id);
						if ($rc) {
							my @today = localtime;	
							my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
							open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        						if ($log_f) {
                						@today = localtime;	
								my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
								flock ($log_f, LOCK_EX) or print STDERR "Could not log change password for $id due to flock error: $!$/"; 
								seek ($log_f, 0, SEEK_END);
		 						print $log_f "$id CHANGE PASSWORD $time\n";
								flock ($log_f, LOCK_UN);	
                						close $log_f;
        						}
							else {
								print STDERR "Could not log change password for $id: $!\n";
							}
							$succ_msg = "<h5>Your password has been changed!</h5><br>You should be redirected to <a href=\"/settings.html\">/settings.html</a> in <span style='font-weight: bold' id='counter'>11s</span>. If you are not, <a href=\"/settings.html\">Click Here</a>"; 
						}
						else {
							print STDERR "Couldn't execute UPDATE users: ", $prep_stmt->errstr, $/;
						}
					}
					else {
						print STDERR "Couldn't prepare UPDATE users: ", $prep_stmt->errstr, $/;
					}
					$con->commit();
					$con->disconnect();
					not_found($succ_msg, 10);
					exit 0;
					}
				}
				}
				else {
					my $error_msg = "<span style='color: red'>A valid password should be atleast 6 characters long.</span>. You should be redirected to <a href=\"/settings.html\">/settings.html</a> in <span style='font-weight: bold' id='counter'>11s</span>. If you are not, <a href=\"/settings.html\">Click Here</a>"; 
					not_found($error_msg, 10);
					exit 0;
				}
			}
			else {
					my $error_msg = "<span style='color: red'>Do not alter the tokens within the HTTP form</span>. You should be redirected to <a href=\"/settings.html\">/settings.html</a> in <span style='font-weight: bold' id='counter'>11s</span>. If you are not, <a href=\"/settings.html\">Click Here</a>"; 
				not_found($error_msg, 10);
				exit 0;
			}
		}
		else {
			$session{"confirm_code"} = $token; 
			my @new_sess_array;
			for my $sess_key (keys %session) {
				push @new_sess_array, $sess_key."=".$session{$sess_key};	
			}
			my $new_sess = join ('&',@new_sess_array);
			
			print "X-Update-Session: $new_sess\r\n";

			$content .=

'<title>Spanj: Exam Management Information System - Change Password</title>
	<script>
		var no_match = 0;
		function confirm_change() {
			var n_pass1 = document.getElementById("new_pwd_1").value;
			var n_pass2 = document.getElementById("new_pwd_2").value;
			var new_content = "";
			if (n_pass1 !== n_pass2) {
				if (no_match++ < 1) {
					new_content += "<p><h5><span style=\"color: red\">The 2 passwords entered do not match. Enter them again to continue.</span></h5>";
					new_content += document.getElementById("pre_conf").innerHTML;	
				}
			}
			else {
				new_content += 
				"<p><h5>Are you sure you want to change your password?</h5>" +
				"<p>" +
				"<form method=\"POST\" action=\"/cgi-bin/settings.cgi?act=chpass\">" +
				"<input type=\"hidden\" name=\"n_pwd\" value=\"" + n_pass1 + "\">" +
				"<input type=\"hidden\" name=\"confirm_code\" value=\"' . $token .'\">" +
				"<table>" +
				"<tr>" +
				"<td><input type=\"submit\" name=\"confirm\" value=\"Confirm\">" +
				"<td><input type=\"button\" name=\"cancel\" value=\"Cancel\" onclick=\"cancel_change()\">" +
				"</table>" +
				"</form>";
			}
			document.getElementById("pre_conf").innerHTML = new_content;
		} 
		function cancel_change() {
			window.location.href = "/settings.html";
		}

	</script>
</head>

<body>

<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/settings.html">

	</iframe>	
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/settings.html">Settings</a> --&gt; <a href="/cgi-bin/settings.cgi?act=chpass">Change Password</a> 
	<h5>Change Password</h5>

<div id="pre_conf"> 

	<table>

	<tr>
	<td><label for="new_pwd_1">New Password</label>
	<td><input type="password" name="new_pwd_1" id="new_pwd_1" value="" size="15">
	<tr>
	<td><label type="text" for="new_pwd_2">Confirm New Password</label>
	<td><input type="password" name="new_pwd_2" id="new_pwd_2" value="" size="15">
	<tr>
	<td><input type="button" name="save" value="Save" onclick="confirm_change()">

	</table>
</div>

</body>
</html>
';
		}

	}

		#chsecqs request
		elsif ($req_act eq "chsecqs") {
			if ($confirmed) {
				if ( exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and ($session{"confirm_code"} eq $auth_params{"confirm_code"}) ) {
					if (exists $auth_params{"sec_q1"} and exists $auth_params{"ans_1"} and exists $auth_params{"sec_q2"} and exists $auth_params{"ans_2"}) {
						if ( length($auth_params{"sec_q1"}) <= 100 or length($auth_params{"sec_q1"}) > 0 or length($auth_params{"sec_q2"}) <= 100 or length($auth_params{"sec_q2"}) > 0) {
							$auth_params{"ans_1"} = lc($auth_params{"ans_1"});
							$auth_params{"ans_2"} = lc($auth_params{"ans_2"});
							$auth_params{"ans_1"} =~ s/[^a-z0-9]//g;
							$auth_params{"ans_2"} =~ s/[^a-z0-9]//g;	

	     						$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});	
							if ($con) {
								my $prep_stmt = $con->prepare("UPDATE users SET sec_qstn1=?,sec_qstn2=?,sec_qstn1_ans=?,sec_qstn2_ans=? WHERE u_id=? LIMIT 1");
					
								if ($prep_stmt) {
									my $rc = $prep_stmt->execute($auth_params{"sec_q1"}, $auth_params{"sec_q2"}, uc(sha1_hex($auth_params{"ans_1"})), uc(sha1_hex($auth_params{"ans_2"})), $id);
									if ($rc) {
										my @today = localtime;	
	                							my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
										open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        									if ($log_f) {
                									@today = localtime;	
											my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
											flock ($log_f, LOCK_EX) or print STDERR "Could not log change security questions for due to flock error: $!$/"; 
											seek ($log_f, 0, SEEK_END);	
                									print $log_f "$id CHANGE SECURITY QUESTIONS( " . $auth_params{"sec_q1"} . ", " . $auth_params{"sec_q2"} . " ) " . "$time\n";
											flock ($log_f, LOCK_UN);	
                									close $log_f;
        									}
										else {
											print STDERR "Could not log change password for $id: $!\n";
										}
									}
									else {
										print STDERR "Couldn't execute UPDATE users: ", $prep_stmt->errstr, $/;
									}
								}
								else {
									print STDERR "Couldn't prepare UPDATE user : ", $prep_stmt->errstr, $/;  
								}
								$con->commit();
								$con->disconnect();
								my $succ_msg = "<h5>Your security questions have been changed!</h5><br>You should be redirected to <a href=\"/settings.html\">/settings.html</a> in <span style='font-weight: bold' id='counter'>11s</span>. If you are not, <a href=\"/settings.html\">Click Here</a>";
								not_found($succ_msg, 10);
								exit 0; 
							}
						}
						else {
							my $error_msg = "<span style='color: red'>Security questions may not be blank or more than 100 characters(10 or so words)</span>. You should be redirected to <a href=\"/settings.html\">/settings.html</a> in <span style='font-weight: bold' id='counter'>11s</span>. If you are not, <a href=\"/settings.html\">Click Here</a>"; 
						not_found($error_msg, 10);
						exit 0;
						}
					}
					else {
						my $error_msg = "<span style='color: red'>You must provide 2 security questions and answers</span>. You should be redirected to <a href=\"/settings.html\">/settings.html</a> in <span style='font-weight: bold' id='counter'>11s</span>. If you are not, <a href=\"/settings.html\">Click Here</a>"; 
						not_found($error_msg, 10);
						exit 0;
					}

				}
				else {
					my $error_msg = "<span style='color: red'>Do not alter the tokens within the HTTP form</span>. You should be redirected to <a href=\"/settings.html\">/settings.html</a> in <span style='font-weight: bold' id='counter'>11s</span>. If you are not, <a href=\"/settings.html\">Click Here</a>"; 
					not_found($error_msg, 10);
					exit 0;
				}		
			}
			else {
				my $current_sec_qstns = "";
     				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});	
				if ($con) {
					my $prep_stmt = $con->prepare("SELECT sec_qstn1,sec_qstn2 FROM users WHERE u_id=? LIMIT 1");
					
					if ($prep_stmt) {
						my $rc = $prep_stmt->execute($id);
						if ($rc) {
							while ( my @valid = $prep_stmt->fetchrow_array() ) {
								if ( defined($valid[0]) and defined($valid[1]) ) {
						
									$current_sec_qstns = "<span style='font-weight: bold'>Current Security Questions:</span><br><br>" .
										"&nbsp;&nbsp;1. " . $valid[0] . "<br><br>" .
										"&nbsp;&nbsp;2. " . $valid[1] . "<br><br>";	
								}
							}
						}
						else {
							print STDERR "Couldn't execute SELECT FROM users: ", $prep_stmt->errstr, $/;
						}	
					}
					else {
						print STDERR "Couldn't prepare SELECT FROM users: ", $prep_stmt->errstr, $/;  
					}	
					$con->disconnect();	
				}
				$content .=

'<title>Spanj: Exam Management Information System - Change Security Questions</title>
	<script>
		var blank_ans = 0;
		var invalid_q = 0;
		function get_opt_label(id) {

			if (typeof id === "number") {
			if (id > 0 && id < 13) {
				switch (id) {
					case 1:
						return "What was the name of your school in class 3?" 
					case 2:
						return "Which month/year did you first meet your significant other(e.g July 2001)?"
					case 3:
						return "What was the middle name of your favourite teacher in high school?";
					case 4:
						return "What is the middle name of your favourite cousin?";
					case 5:
						return "Which is your favourite T.V show?";
					case 6:
						return "Who is your favourite female Kenyan gospel musician?"
					case 7:
						return "Who is your favourite male Kenyan secular(non-gospel) musician?";
					case 8:
						return "What is the middle name of your favourite female news anchor?";
					case 9:
						return "What is the middle name of your favourite male news anchor?";
					case 10:
						return "What was the middle name of your favourite cube/room/dorm-mate in Form 3?";
					case 11:
						return "What was the middle name of your least favourite teacher in high school?";
					case 12:
						return "What was your nickname in primary school?";
				}
			}
			}
			return null;
		}
		function check_type_own(qstn) {
			var curr_val = "";
			if (qstn === 1) {
				var opt_1 = document.getElementById("sec_q1").value;
				if (opt_1 === "13") {	
					if (document.getElementById("own_secq1") !== null) {
						curr_val = document.getElementById("own_secq1").value;
						document.getElementById("type_own_1").innerHTML = "<tr><td><td><input type=\"text\" size=\"75\" maxlength=\"100\" value=\"" + curr_val + "\" name=\"own_secq1\" id=\"own_secq1\">";
					}
					else {
						document.getElementById("type_own_1").innerHTML = "<tr><td><td><input type=\"text\" size=\"75\" maxlength=\"100\" value=\"\" name=\"own_secq1\" id=\"own_secq1\">";
					}
				}
				else {
					document.getElementById("type_own_1").innerHTML = "";
				}
			}
			else if (qstn === 2 ) {
				var opt_2 = document.getElementById("sec_q2").value;
				if (opt_2 === "13") {	
					if (document.getElementById("own_secq2") !== null) {
						curr_val = document.getElementById("own_secq2").value;
						document.getElementById("type_own_2").innerHTML = "<tr><td><td><input type=\"text\" size=\"75\" maxlength=\"100\" value=\"" + curr_val + "\" name=\"own_secq2\" id=\"own_secq2\">";
					}
					else {
						document.getElementById("type_own_2").innerHTML = "<tr><td><td><input type=\"text\" size=\"75\" maxlength=\"100\" value=\"\" name=\"own_secq2\" id=\"own_secq2\">";
					}
				}
				else {
					document.getElementById("type_own_2").innerHTML = "";
				}
			}
		}
		function confirm_change() {
			var new_content = "";
			
			var sec_q1 = document.getElementById("sec_q1").value;
			var sec_q2 = document.getElementById("sec_q2").value;
			
			var sec_q1_to_num = parseInt(sec_q1);
			var sec_q2_to_num = parseInt(sec_q2);		

			if (sec_q1_to_num > 0 && sec_q1_to_num < 14 && sec_q2_to_num > 0 && sec_q2_to_num < 14) {

				var ans_1  = document.getElementById("sec_a1").value;	
				var ans_2  = document.getElementById("sec_a2").value;
				if (ans_1 === "" || ans_2 === ""  || ans_1 === null || ans_2 === null) {
					if (blank_ans++ < 1) {
						new_content += "<span style=\"color: red\">You must provide an answer to each security question.</span>";
						new_content += "<br>" + document.getElementById("pre_conf").innerHTML;
						document.getElementById("pre_conf").innerHTML = new_content;
					}
				}
				else {
					if (sec_q1 !== sec_q2) { 
						if (sec_q1_to_num == 13) {
							sec_q1 = document.getElementById("own_secq1").value; 
						}
						else {
							sec_q1 = get_opt_label(sec_q1_to_num);
						}
						if (sec_q2_to_num == 13) {
							sec_q2 = document.getElementById("own_secq2").value;
						}
						else {
							sec_q2 = get_opt_label(sec_q2_to_num);
						}
						new_content = 
						"Clicking \'confirm\' will change your security questions to:<br><br>" +
						"<table cellpadding=\"2\" border=1>" +
						"<tr><th><th>Security Question<th>Answer" +
						"<tr><td>1.<td>" + sec_q1 + "<td>" + ans_1 +
						"<tr><td>2.<td>" + sec_q2 + "<td>" + ans_2 +
						"</table><br>" +
						"<form method=\"POST\" action=\"/cgi-bin/settings.cgi?act=chsecqs\">" +
						"<input type=\"hidden\" name=\"sec_q1\" value=\"" + sec_q1 + "\">" +
						"<input type=\"hidden\" name=\"ans_1\" value=\"" + ans_1 + "\">" +
						"<input type=\"hidden\" name=\"sec_q2\" value=\"" + sec_q2 + "\">" +
						"<input type=\"hidden\" name=\"ans_2\" value=\"" + ans_2 + "\">" +
						"<input type=\"hidden\" name=\"confirm_code\" value=\"' . $token . '\">" +
						"<table cellpadding=\"2\">" +
						"<tr><td><input type=\"submit\" name=\"submit\" value=\"Confirm\">" +
						"<td><input type=\"button\" name=\"cancel\" value=\"Cancel\" onclick=\"cancel_change()\">" +
						"</form>" +
						"</table>";
						document.getElementById("pre_conf").innerHTML = new_content;
					}
					else if(sec_q1 !== "13") {
						new_content += "<span style=\"color: red\">You must provide two DIFFERENT security questions.</span>";
						new_content += "<br>" + document.getElementById("pre_conf").innerHTML;
						document.getElementById("pre_conf").innerHTML = new_content;

					}
				}
			}
			else {
				if (invalid_q++ < 1) {
					new_content += "<span style=\"color: red\">Invalid security question. Select one from the options given or type your own.</span>";
					new_content += "<br>" + document.getElementById("pre_conf").innerHTML;
					document.getElementById("pre_conf").innerHTML = new_content;
				}
			}
			
			return 0;
		} 
		function cancel_change() {
			window.location.href = "/settings.html";	
		}

	</script>
</head>

<body>

<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/settings.html">

	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/settings.html">Settings</a> --&gt; <a href="/cgi-bin/settings.cgi?act=chsecqs">Change Security Questions</a> 

	<h5>Change Security Questions</h5>
	<p>'. $current_sec_qstns .
'
	<div id="pre_conf"> 
	<span style="font-weight: bold">Select your new Security Questions</span><br>
	<table cellpadding="3">
<tr>
<td><label for="sec_q1">1. Security Question</label>
<td>
<select name="sec_q1" id="sec_q1" onclick="check_type_own(1)">
<option value="1">What was the name of your school in class 3?(indicate the full name of the school e.g. Karagita Primary School)</option> 
<option value="2">Which month &amp; year(e.g July 2001) did you first meet your significant other?</option> 
<option value="3">What was the middle name of your favourite teacher in high school?</option> 
<option value="4">What is the middle name of your favourite cousin?</option>
<option value="5">Which is your favourite T.V show?</option> 
<option value="6">Who is your favourite female Kenyan gospel musician?</option> 
<option value="7">Who is your favourite male Kenyan secular(non-gospel) musician?</option> 
<option value="8">What is the middle name of your favourite female news anchor?</option> 
<option value="9">What is the middle name of your favourite male news anchor?</option> 
<option value="10">What was the middle name of your favourite cube/room/dorm-mate in Form 3?</option> 
<option value="11">What was the middle name of your least favourite teacher in high school?</option>
<option selected value="12">What was your nickname in primary school?</option>
<option value="13">[Type your own question]</option> 
</select>
<span id="type_own_1"></span>
<tr>
<td><label for="sec_a1">Answer:</label>
<td><input type="text" id="sec_a1" name="sec_a1" value="" size="40">
<p>
<tr>
<td><label for="sec_q2">2. Security Question</label>

<td>
<select name="sec_q1" id="sec_q2" onclick="check_type_own(2)">
<option value="1">What was the name of your school in class 3?(indicate the full name of the school e.g. Karagita Primary School)</option> 
<option value="2">Which month &amp; year(e.g July 2001) did you first meet your significant other?</option> 
<option value="3">What was the middle name of your favourite teacher in high school?</option> 
<option value="4">What is the middle name of your favourite cousin?</option>
<option value="5">Which is your favourite T.V show?</option> 
<option value="6">Who is your favourite female Kenyan gospel musician?</option> 
<option value="7">Who is your favourite male Kenyan secular(non-gospel) musician?</option> 
<option value="8">What is the middle name of your favourite female news anchor?</option> 
<option value="9">What is the middle name of your favourite male news anchor?</option> 
<option selected value="10">What was the middle name of your favourite cube/room/dorm-mate in Form 3?</option> 
<option value="11">What was the middle name of your least favourite teacher in high school?</option>
<option value="12">What was your nickname in primary school?</option>
<option value="13">[Type your own question]</option> 
</select>
<span id="type_own_2"></span>
<tr>
<td><label for="sec_a2">Answer: </label>
<td><input type="text" id="sec_a2" name="sec_a2" value="" size="40">
<tr>
<td><input type="button" name="save" value="Save" onclick="confirm_change()">
</table>
</div>
</body>
</html>
';

				$session{"confirm_code"} = $token; 
				my @new_sess_array;
				for my $sess_key (keys %session) {
					push @new_sess_array, $sess_key."=".$session{$sess_key};	
				}
				my $new_sess = join ('&',@new_sess_array);
			
				print "X-Update-Session: $new_sess\r\n";
			}
		}
		
		#chsysvars request
		else {
			if ($confirmed) {
 	if ( exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and ($session{"confirm_code"} eq $auth_params{"confirm_code"}) ) {
				delete $auth_params{"confirm"};
				delete $auth_params{"confirm_code"};
				if (scalar(keys %auth_params)  > 0) {
					$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});	
					if ($con) {
					my %to_add;
					my %to_delete;
					for my $auth_param (keys %auth_params) {
						if ($auth_params{$auth_param} eq "") {
							$to_delete{$auth_param} = $auth_params{$auth_param};
						}
						else {
							$to_add{$auth_param} = $auth_params{$auth_param};
						}
					}
					my $num_adds = 	scalar(keys %to_add);

					if ($num_adds > 0) {
						my @adds;

						for (my $i = 0; $i < $num_adds; $i++) {
							push @adds, "(?, ?, ?, ?)";
						}

						my $replace_clause = join(', ', @adds);
						my @new_vals;
						my @log_msg;
						for my $ky (keys %to_add) {
							push @new_vals, $id, $ky, $to_add{$ky}, $id. "-". $ky;
							push @log_msg, "($id, $ky, $to_add{$ky}, $id-$ky)";
						}


						my $prep_stmt = $con->prepare("REPLACE INTO vars VALUES $replace_clause");
								
						if ($prep_stmt) {
						
							my $rc = $prep_stmt->execute(@new_vals);
							if ($rc) {
								my @today = localtime;	
								my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

								open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        							if ($log_f) {
                							@today = localtime;	
									my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
									flock ($log_f, LOCK_EX)  or print STDERR "Could not log add sysvars due to flock error: $!$/";;
									seek($log_f, 0, SEEK_END);
                							print $log_f "$id ADD SYSVARS " . join(', ', @log_msg) . " $time\n";	
									flock ($log_f, LOCK_UN);
                							close $log_f;
        							}
								else {
									print STDERR "Could not log change password for $id: $!\n";
								}
							}
							else {
								print STDERR "Could not execute REPLACE INTO vars: ", $prep_stmt->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare REPLACE INTO vars: ", $prep_stmt->errstr, $/;  
						}
					}

					my $num_dels = 	scalar(keys %to_delete);

					if ($num_dels > 0) {
						my @dels;
					
						for (my $i = 0; $i < $num_dels; $i++) {
							push @dels, "id=?";
						}

						my $delete_clause = join(' OR ', @dels);

						my @del_vals;
						my @log_msg = ();

						for my $ky (keys %to_delete) {
							push @del_vals, $id."-".$ky;
							push @log_msg, "$id-$ky";
						}

						my $prep_stmt = $con->prepare("DELETE FROM vars WHERE $delete_clause");
								
						if ($prep_stmt) {
						
							my $rc = $prep_stmt->execute(@del_vals);
							if ($rc) {
								my @today = localtime;	
								my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
								open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        							if ($log_f) {
                							@today = localtime;	
									my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
									flock($log_f, LOCK_EX)  or print STDERR "Could not log delete sysvars due to flock error: $!$/";;
									seek($log_f, 0, SEEK_END);
	         							print $log_f "$id DELETE SYSVARS " . join(', ', @log_msg) . " $time\n";	
									flock($log_f, LOCK_UN);
                							close $log_f;
        							}
								else {
									print STDERR "Could not log change password for $id: $!\n";
								}
							}
							else {
								print STDERR "Couldn't execute DELETE FROM vars: ", $prep_stmt->errstr, $/;
							}	
						}
						else {
							print STDERR "Couldn't prepare DELETE FROM vars: ", $prep_stmt->errstr, $/;  
						}
					}
					$con->commit();	
					$con->disconnect();	
							my $succ_msg = "<h5>Your system variables have been updated!</h5><br>You should be redirected to <a href=\"/settings.html\">/settings.html</a> in <span style='font-weight: bold' id='counter'>11s</span>. If you are not, <a href=\"/settings.html\">Click Here</a>";
							not_found($succ_msg, 10);
							exit 0;
					}

				}
				else {
					my $error_msg = "<span style='color: red'>No edits or additions were made to the system variables!</span>.<br>You should be redirected to <a href=\"/settings.html\">/settings.html</a> in <span style='font-weight: bold' id='counter'>11s</span>. If you are not, <a href=\"/settings.html\">Click Here</a>"; 
						not_found($error_msg, 10);
						exit 0;

				}
			}
			else {
					my $error_msg = "<span style='color: red'>Do not alter the tokens within the HTTP form</span>. You should be redirected to <a href=\"/settings.html\">/settings.html</a> in <span style='font-weight: bold' id='counter'>11s</span>. If you are not, <a href=\"/settings.html\">Click Here</a>"; 
					not_found($error_msg, 10);
					exit 0;
			}	
			}
			else {
				my %k_v;
     				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});	
				if ($con) {
					my $prep_stmt = $con->prepare("SELECT name,value FROM vars WHERE owner=?");
					
					if ($prep_stmt) {
						my $rc = $prep_stmt->execute($id);
						if ($rc) {
							while (my @valid = $prep_stmt->fetchrow_array()) {
								$k_v{htmlspecialchars($valid[0])} = htmlspecialchars($valid[1]);	
							}	
						}
						else {
							print STDERR "Could not execute SELECT FROM vars: ", $prep_stmt->errstr, $/;
						}	
					}
					else {
						print STDERR "Could not prepare SELECT FROM vars: ", $prep_stmt->errstr, $/;  
					}
				}	
				$con->disconnect();
				my $current_vars = '';
				my @k_v_keys = keys %k_v; 
				my $cntr = 0;
				if ( scalar(@k_v_keys) > 0 ) {
					$current_vars .= '<table border="1" cellpadding="2"><tr><th>Name<th>Value<th>';
					for my $key (@k_v_keys) {
						$current_vars .= '<tr><td><input type="hidden" id="pre_' . ++$cntr . '_key" name="pre_' .$cntr . '_key" value="'. $key. '"><label for="pre_' . $cntr . '_val">' . $key . '</label><td><input disabled type="text" size="60" maxlength="300" id="pre_'.$cntr . '_val" value="' . $k_v{$key} . '" name="pre_' . $cntr . '_val"><td><input type="button" name="enable" value="Edit" onclick="edit(\'' . $cntr . '\')">';
					}
					$current_vars .= '</table>';
				}
				else {
					$current_vars = '<em>You have no system variables defined.</em>';
				}
				$content .=
'<title>Spanj: Exam Management Information System - Change System Variables</title>
<script>
var adds_cntr = 0;
var adds = new Array();

function add_new() {
	var add_table = "<table>";
	for (var i = 0; i < adds.length; i++) {
		var key = adds[i] + "_key";	
		var key_content = document.getElementById(key).value; 
		var val = adds[i] + "_val";	
		var val_content = document.getElementById(val).value;
 	
		add_table += "<tr><td><input type=\"text\" name=\"" + adds[i] + "_key\" id=\"" + adds[i] + "_key\" size=\"32\" maxlength=\"64\" value=\"" +key_content + "\"><td><input type=\"text\" name=\"" + adds[i] + "_val\" id=\"" + adds[i] + "_val\" size=\"60\" maxlength=\"300\" value=\"" + val_content + "\">";	
	}
	++adds_cntr;
	add_table += "<tr><td><input type=\"text\" name=\"add_" + (adds_cntr).toString() + "_key\" id=\"add_" + (adds_cntr).toString() + "_key\" size=\"32\" maxlength=\"64\" value=\"\"><td><input type=\"text\" name=\"add_" + adds_cntr.toString() + "_val\" id=\"add_" + adds_cntr.toString() + "_val\" size=\"60\" maxlength=\"300\" value=\"\">";
	adds.push("add_" + adds_cntr.toString());
	document.getElementById("additions").innerHTML = add_table;
	document.getElementById("save").disabled = 0;
}

function edit(id) {
	var object_id = "pre_" + id + "_val";
	if ( document.getElementById(object_id) != null ) {
		var inactive = document.getElementById(object_id).disabled;
		if (inactive) {	
			document.getElementById(object_id).disabled = 0;	
			adds.push("pre_" + id);
			document.getElementById("save").disabled = 0;
		}
		else {	
			document.getElementById(object_id).disabled = 1;	
			for (var j = 0; j < adds.length; j++) {
				if (adds[j] === "pre_" + id) {
					adds.splice(j, 1);
					break;
				}
			}	
			if (adds.length == 0) {	
				document.getElementById("save").disabled = 1;
			}
		}
	}
}

function save() {
	if (adds.length > 0) {
		
	
		var new_content = "<em>Clicking \'confirm\' will add the following variables to the database</em><p>";
		new_content += "<form method=\"POST\" action=\"/cgi-bin/settings.cgi?act=chsysvars\">";
		new_content += "<table border=\"1\" cellpadding=\"1\">";
		new_content += "<th>Name<th>Value";
		for (var i = 0; i < adds.length; i++) {
			var key = adds[i] + "_key";	
			var key_content = document.getElementById(key).value; 
			var val = adds[i] + "_val";
			var val_content = document.getElementById(val).value;
 
			new_content += "<tr><td><input type=\"hidden\" name=\"" + quote(key_content) + "\" value=\"" + quote(val_content) + "\"><label>" + htmlspecialchars(key_content) + "</label>";
			new_content += "<td><label>" + htmlspecialchars(val_content) + "</label>";	
		}
		new_content += "</table><table><tr><td><input type=\"submit\" name=\"confirm\" value=\"Confirm\"><td><input type=\"button\" name=\"cancel\" value=\"Cancel\" onclick=\"cancel_change()\">";
		new_content += "<input type=\"hidden\" name=\"confirm_code\" value=\"' . $token . '\">";
		new_content += "</form></table>";
		document.getElementById("pre_conf").innerHTML = new_content;
	}
	else {
		alert ("Nothing to save!");
	}
}

function quote(to_clean) {
	to_clean = to_clean.replace(/"/g, "\'\'");
	return to_clean;
}

function htmlspecialchars(to_clean) {
	to_clean = to_clean.replace(/</g,  "&#60;");
	to_clean = to_clean.replace(/>/g,  "&#62;");
	to_clean = to_clean.replace(/\'/g, "&#39;");
	to_clean = to_clean.replace(/"/g,  "&#34;"); 
	return to_clean;
}

function cancel_change() {
	window.location.href = "/settings.html";	
}
</script>
</head>
<body>

<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/settings.html">

	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/settings.html">Settings</a> --&gt; <a href="/cgi-bin/settings.cgi?act=chsysvars">Change System Variables</a><div id="pre_conf"><p><input type="button" name="Add_new" value="Add New" onclick="add_new()"><p><span id="additions"></span><br><hr><p>' 
. 
$current_vars
.
'<p><input disabled type="button" name="save" value="Save" id="save" onclick="save()"></div>
</body>
</html>
';
				$session{"confirm_code"} = $token; 
				my @new_sess_array;
				for my $sess_key (keys %session) {
					push @new_sess_array, $sess_key."=".$session{$sess_key};	
				}
				my $new_sess = join ('&',@new_sess_array);	
				print "X-Update-Session: $new_sess\r\n";
			}
		}

		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=iso-8859-1\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		print "\r\n";
		print $content;
	}

	else {
		my $error_msg = "<span style='color: red'>The resource you requested was not found</span>.<br>You should be redirected to <a href=\"/settings.html\">/settings.html</a> in <span style='font-weight: bold' id='counter'>11s</span>. If you are not, <a href=\"/settings.html\">Click Here</a>"; 
		not_found($error_msg, 10);
		exit 0;
	}
}

else {

	print "Status: 302 Moved Temporarily\r\n";
	print "Location: /login.html?cont=/settings.html\r\n";
	print "Content-Type: text/html; charset=ISO-8859-1\r\n";
       	my $res = 
               	"<html>
               	<head>
		<title>Spanj: Exam Management Information System - Redirect Failed</title>
		</head>
         	<body>
                You should have been redirected to <a href=\"/login.html?cont=/settings.html\">/login.html?cont=/settings.html</a>. If you were not, <a href=\"/settings.html\">Click Here</a> 
		</body>
                </html>";

	my $content_len = length($res);	
	print "Content-Length: $content_len\r\n";
	print "\r\n";
	print $res;
}



sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub not_found {
		my $menu = "";
		if ($req_act eq "chusername") {
			$menu = qq{ <p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/settings.html">Settings</a> --&gt; <a href="/cgi-bin/settings.cgi?act=chusername">Change Username</a>};
		}

		elsif ($req_act eq "chpass") {
			$menu = qq{<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/settings.html">Settings</a> --&gt; <a href="/cgi-bin/settings.cgi?act=chpass">Change Password</a>} 
		}

		elsif ($req_act eq "chsecqs") {
			$menu = qq{<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/settings.html">Settings</a> --&gt; <a href="/cgi-bin/settings.cgi?act=chsecqs">Change Security Questions</a>}; 
		}

		elsif ($req_act eq "chsysvars") {
			$menu = qq{<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/settings.html">Settings</a> --&gt; <a href="/cgi-bin/settings.cgi?act=chsysvars">Change System Variables</a>} 
		}

		my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	$menu
	<hr> 
};

		my $msg= $_[0];
		my $delay = $_[1];
		unless ($delay =~ /^\d+$/) {
			$delay = 10;
		}

		print "Status: 200 OK\r\n";
		print "Refresh: $delay; url=/settings.html\r\n";
		print "Content-Type: text/html; charset=ISO-8859-1\r\n";

    	my $res = 
               	"<html>
               	<head>

		<title>Spanj: Exam Management Information System - Unknown Resource</title>

		<script>

		function count_dwn() {
			var cntr = $delay;
			var counter_obj = window.setInterval(
			function() {
				if (cntr > 0 ) {
					document.getElementById('counter').innerHTML = cntr + 's';
					cntr--; 
				}
				else {	
					window.clearInterval(counter_obj);
					return;
				}
			}, 1000);

		}
		
		</script>

		</head>

         	<body onload='count_dwn()'>
		$header
		$msg
		</body>
                </html>";

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;

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

